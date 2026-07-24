"""What a signed-in user may do to their own credentials.

Separate from the administrator flows because the authorization rule is
different in kind: there is no scope to check, only the constraint that the
subject is the caller. Every method here reads the user from `actor.id` and
never from a parameter, so no caller can pass someone else's identifier.

See docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

from dataclasses import replace

from app.application.use_cases.accept_invitation import Enrolment
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.application.use_cases.recovery_codes import reissue_recovery_codes
from app.domain.entities.actor import Actor
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
    NotAuthenticatedError,
    WeakPasswordError,
)
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


class ManageOwnAccount:
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

    async def change_password(
        self, actor: Actor, *, session_id: str, current_password: str, new_password: str
    ) -> None:
        user = await self._require_self(actor)

        current_hash = user.password_hash
        if current_hash is None:
            # A tailnet-only account has no password to change. It reaches this
            # only through the public entrance, which it cannot authenticate
            # against, so this is defence against a wiring mistake rather than
            # a reachable state.
            raise InvalidCredentialsError(detail=f"user {user.id} has no local password")

        if not await self._hasher.verify(current_password, current_hash):
            await self._audit.record(
                actor, "user.password_changed", target=user.id, outcome="denied"
            )
            raise InvalidCredentialsError(detail=f"wrong current password user={user.id}")

        if current_password == new_password:
            # Checked here rather than left to the strength estimator, which
            # would happily accept a strong password being set to itself and
            # report a successful change that changed nothing.
            raise WeakPasswordError("That is the password you are already using.")

        self._policy.assert_acceptable(new_password, user_inputs=[user.login, user.display_name])

        await self._users.save(replace(user, password_hash=await self._hasher.hash(new_password)))
        # Every other session dies. The usual reason for changing a password is
        # that the old one may be in someone else's hands, and leaving their
        # session alive would make the change cosmetic.
        await self._sessions.invalidate_others(user.id, session_id, self._clock.now())
        await self._audit.record(actor, "user.password_changed", target=user.id)

    async def begin_totp_reenrolment(self, actor: Actor) -> Enrolment:
        """Issue a new secret without touching the working one.

        The candidate is held in the cache for minutes, not written to the user
        row, so abandoning the flow leaves the existing authenticator intact.
        Writing it to the row first would break the second factor for anyone
        who opened this screen and closed it again.
        """
        user = await self._require_self(actor)
        secret = self._totp.generate_secret()
        await self._pending.put(user.id, secret)

        return Enrolment(
            login=user.login,
            secret=secret,
            provisioning_uri=self._totp.provisioning_uri(secret, user.login, self._issuer),
        )

    async def pending_provisioning_uri(self, actor: Actor) -> str:
        """Backs the QR image endpoint, which cannot carry the secret in a
        query string: an image URL lands in browser history and in any proxy
        log between here and the client."""
        user = await self._require_self(actor)
        return self._totp.provisioning_uri(
            await self._pending.require(user.id), user.login, self._issuer
        )

    async def confirm_totp_reenrolment(
        self, actor: Actor, *, session_id: str, code: str
    ) -> list[str]:
        """Swap the secret in and return a fresh set of recovery codes."""
        user = await self._require_self(actor)
        secret = await self._pending.require(user.id)

        # `None` for the last counter: the stored one belongs to the secret
        # being replaced, and comparing across secrets would reject a
        # legitimate code or accept a stale one depending on clock drift.
        counter = self._totp.verify(secret, code, None)

        await self._users.save(
            replace(
                user,
                totp_secret=self._secret_box.encrypt(secret),
                totp_last_counter=counter,
            )
        )
        await self._pending.clear(user.id)

        codes = await reissue_recovery_codes(self._invitations, self._tokens, user.id)
        await self._sessions.invalidate_others(user.id, session_id, self._clock.now())
        await self._audit.record(actor, "user.totp_reenrolled", target=user.id)
        return codes

    async def _require_self(self, actor: Actor) -> User:
        user = await self._users.get(actor.id)
        if user is None or user.disabled_at is not None:
            # The session outlived the account. 401 rather than 404, because
            # the correct client behaviour is to sign out, not to retry.
            raise NotAuthenticatedError(detail=f"no usable user for actor {actor.id}")
        return user
