"""Redeeming an invitation or a reset link.

Both are unauthenticated: the token is the credential. Every failure raises
the same `InvitationInvalidError`, so unknown, expired, consumed, and
wrong-purpose tokens are indistinguishable and the endpoint cannot be used to
learn which links once existed.

Enrolment spans two calls and the secret has to survive between them; where it
waits, and why not in the user row, is in `pending_enrolment.py`. The
consequence here is that `begin` writes nothing to the database, which is the
right shape for an endpoint an unauthenticated caller can reach.

See docs/architecture/security.md sections 5.3 and 5.4.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.application.use_cases.recovery_codes import reissue_recovery_codes
from app.domain.entities.actor import Actor, Role
from app.domain.entities.invitation import Invitation, InvitationPurpose
from app.domain.entities.user import User
from app.domain.exceptions import InvitationInvalidError
from app.domain.ports.repositories import InvitationRepositoryPort, UserRepositoryPort
from app.domain.ports.security_ports import (
    AuditPort,
    PasswordHasherPort,
    PasswordPolicyPort,
    SecretBoxPort,
    SessionRegistryPort,
    TotpPort,
)
from app.domain.services.token_service import TokenService
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class Enrolment:
    login: str
    secret: str
    provisioning_uri: str


class AcceptInvitation:
    def __init__(
        self,
        users: UserRepositoryPort,
        invitations: InvitationRepositoryPort,
        tokens: TokenService,
        totp: TotpPort,
        hasher: PasswordHasherPort,
        policy: PasswordPolicyPort,
        secret_box: SecretBoxPort,
        pending: PendingEnrolment,
        sessions: SessionRegistryPort,
        audit: AuditPort,
        clock: Clock,
        *,
        issuer: str,
    ) -> None:
        self._users = users
        self._invitations = invitations
        self._tokens = tokens
        self._totp = totp
        self._hasher = hasher
        self._policy = policy
        self._secret_box = secret_box
        self._pending = pending
        self._sessions = sessions
        self._audit = audit
        self._clock = clock
        self._issuer = issuer

    # --- onboarding ------------------------------------------------------

    async def begin(self, token: str) -> Enrolment:
        """Validate the link and return provisioning material.

        Called before the form renders, so an expired or already-used link
        fails immediately rather than after the recipient has chosen a
        password and typed a code.

        Idempotent while the candidate is still held, so refreshing the page
        does not silently invalidate the QR that was just scanned. Once it has
        expired a fresh one is issued and the recipient re-scans, which is the
        recoverable failure the short lifetime buys.
        """
        user = await self._require_pending_user(token)

        secret = await self._pending.get(user.id)
        if secret is None:
            secret = self._totp.generate_secret()
            await self._pending.put(user.id, secret)

        return Enrolment(
            login=user.login,
            secret=secret,
            provisioning_uri=self._totp.provisioning_uri(secret, user.login, self._issuer),
        )

    async def complete(self, token: str, password: str, totp_code: str) -> list[str]:
        """Consume the invitation and return the recovery codes.

        Ordering is the security-relevant part. Everything that can fail on
        the caller's input is checked first, so a mistyped code does not burn
        a single-use link. The atomic claim comes next, and only then is the
        account written, so two requests racing on one link cannot both set a
        password.
        """
        invitation = await self._require_invitation(token, InvitationPurpose.ONBOARD)
        user = await self._require_user(invitation.user_id)
        if user.can_use_public_entrance:
            raise InvitationInvalidError(detail=f"user {user.id} already enrolled")

        secret = await self._pending.require(user.id)

        self._policy.assert_acceptable(password, user_inputs=[user.login, user.display_name])

        # `None` for the last counter: this is a first enrolment, and proving
        # the authenticator produces a current code is the whole point of the
        # step. The accepted counter is stored so the code cannot be replayed
        # into the login that immediately follows.
        counter = self._totp.verify(secret, totp_code, None)

        now = self._clock.now()
        if not await self._invitations.consume(invitation.id, now):
            raise InvitationInvalidError(detail=f"invitation {invitation.id} already claimed")

        # Both credential columns are set in one write. `users` constrains them
        # to be null together, so anything that set only one would be rejected
        # by the database rather than producing a password-only account.
        user = replace(
            user,
            password_hash=await self._hasher.hash(password),
            totp_secret=self._secret_box.encrypt(secret),
            totp_last_counter=counter,
        )
        await self._users.save(user)
        await self._pending.clear(user.id)

        codes = await reissue_recovery_codes(self._invitations, self._tokens, user.id)
        await self._audit.record(_self_actor(user), "user.invitation_accepted", target=user.id)
        return codes

    # --- password reset --------------------------------------------------

    async def describe_reset(self, token: str) -> str:
        """Returns the login the link belongs to, so the form can show whose
        account is being reset. Nothing else: the token holder has not proven
        they are that person yet."""
        invitation = await self._require_invitation(token, InvitationPurpose.PASSWORD_RESET)
        return (await self._require_user(invitation.user_id)).login

    async def consume_reset(self, token: str, password: str) -> None:
        """Set a new password from an administrator-issued link.

        No second factor here, and that is not a gap: the reset only replaces
        the password, and the next login still requires TOTP. Every existing
        session is invalidated, because the reason for a reset is usually that
        the previous credential is in someone else's hands.
        """
        invitation = await self._require_invitation(token, InvitationPurpose.PASSWORD_RESET)
        user = await self._require_user(invitation.user_id)

        self._policy.assert_acceptable(password, user_inputs=[user.login, user.display_name])

        now = self._clock.now()
        if not await self._invitations.consume(invitation.id, now):
            raise InvitationInvalidError(detail=f"reset {invitation.id} already claimed")

        await self._users.save(replace(user, password_hash=await self._hasher.hash(password)))
        await self._sessions.invalidate_all(user.id, now)
        await self._audit.record(_self_actor(user), "user.password_reset_consumed", target=user.id)

    # --- shared ----------------------------------------------------------

    async def _require_invitation(self, token: str, purpose: InvitationPurpose) -> Invitation:
        invitation = await self._invitations.get_by_token_hash(self._tokens.hash_token(token))
        if invitation is None:
            raise InvitationInvalidError(detail="no such token")
        if invitation.purpose != purpose:
            # A reset link presented to the onboarding endpoint, or the
            # reverse. Same error: the caller learns nothing about which.
            raise InvitationInvalidError(detail=f"wrong purpose {invitation.purpose}")
        if not invitation.is_usable(self._clock.now()):
            raise InvitationInvalidError(detail=f"expired or consumed {invitation.id}")
        return invitation

    async def _require_user(self, user_id: str) -> User:
        user = await self._users.get(user_id)
        if user is None or user.disabled_at is not None:
            raise InvitationInvalidError(detail=f"no usable user {user_id}")
        return user

    async def _require_pending_user(self, token: str) -> User:
        invitation = await self._require_invitation(token, InvitationPurpose.ONBOARD)
        user = await self._require_user(invitation.user_id)
        if user.can_use_public_entrance:
            raise InvitationInvalidError(detail=f"user {user.id} already enrolled")
        return user


def _self_actor(user: User) -> Actor:
    """The audit subject for an unauthenticated flow.

    These actions are performed by the account holder against their own
    account while holding a valid token, so recording them as the platform or
    as the issuing administrator would both misattribute them. `source` is
    `local` because that is the entrance they arrived through.
    """
    return Actor(
        id=user.id,
        display=user.login,
        role=Role(user.role),
        source="local",
        scopes=frozenset(),
    )
