"""Creating accounts and issuing single-use links.

**The platform never transmits a credential.** An administrator creates an
account with no password and no second factor, and receives a link to deliver
out of band by whatever channel suits the recipient. That avoids emailing a
password, avoids a temporary-password state nobody remembers to change, and
keeps SMTP out of Phase 1 entirely. See docs/architecture/security.md
section 5.4.

The plaintext token is returned exactly once, from these calls. Only its hash
is stored, so nobody with database access can reconstruct a working link, and
nobody can re-read one that was closed by accident: it has to be reissued,
which invalidates the earlier one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.invitation import Invitation, InvitationPurpose
from app.domain.entities.user import User
from app.domain.exceptions import UserAlreadyExistsError, UserNotFoundError
from app.domain.ports.repositories import InvitationRepositoryPort, UserRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.domain.services.grantable_roles import assert_may_grant
from app.domain.services.token_service import TokenService
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation_id: str
    user: User
    token: str
    """Plaintext, and the only copy that will ever exist."""

    expires_at: datetime
    purpose: InvitationPurpose


class IssueInvitation:
    def __init__(
        self,
        users: UserRepositoryPort,
        invitations: InvitationRepositoryPort,
        tokens: TokenService,
        audit: AuditPort,
        authz: AuthorizationPort,
        clock: Clock,
        *,
        ttl_seconds: int,
    ) -> None:
        self._users = users
        self._invitations = invitations
        self._tokens = tokens
        self._audit = audit
        self._authz = authz
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)

    async def create_account(
        self,
        actor: Actor,
        *,
        login: str,
        display_name: str,
        role: Role,
        tenant_id: str | None = None,
    ) -> IssuedInvitation:
        self._authz.require(actor, Scope.USER_WRITE)
        # `USER_WRITE` says an account may be created, not that it may be
        # created with any role. Without this a `tenant_admin` invites an
        # `admin`, and the response carries the single-use link to onboard as
        # one. See domain/services/grantable_roles.py.
        assert_may_grant(self._authz, actor, role)

        normalised = login.strip().lower()
        if await self._users.get_by_login(normalised) is not None:
            raise UserAlreadyExistsError(detail=f"login={normalised}")

        # `tenant_id` is set explicitly only when creating a tenant's first
        # administrator (ManageTenants), where the target tenant is not the
        # caller's. In the ordinary invite the argument is omitted and the
        # tenant-scoped user repository stamps the caller's tenant on write.
        extra = {"tenant_id": tenant_id} if tenant_id is not None else {}
        user = User(
            id=str(uuid.uuid4()),
            login=normalised,
            display_name=display_name.strip() or normalised,
            role=role,
            **extra,  # type: ignore[arg-type]
        )
        await self._users.save(user)
        # Read back for `created_at`, which the database assigns. Returning
        # the unsaved entity made the frontend's parse throw after the account
        # existed, taking the invitation link with it — and that link is the
        # only copy, since only its hash is stored.
        user = await self._users.get(user.id) or user

        issued = await self._issue(user, InvitationPurpose.ONBOARD)
        await self._audit.record(
            actor,
            "user.invited",
            target=user.id,
            detail={"login": user.login, "role": role.value},
        )
        return issued

    async def reissue_onboarding(self, actor: Actor, *, user_id: str) -> IssuedInvitation:
        """For a link that expired or never arrived.

        Refused once the account is complete, because at that point the
        recipient has credentials and the correct remedy is a password reset.
        Issuing an onboarding link instead would let an administrator silently
        replace a working second factor.
        """
        self._authz.require(actor, Scope.USER_WRITE)
        user = await self._require_user(user_id)

        if user.can_use_public_entrance:
            raise UserAlreadyExistsError(detail=f"user {user.id} already enrolled")

        issued = await self._issue(user, InvitationPurpose.ONBOARD)
        await self._audit.record(actor, "user.invitation_reissued", target=user.id)
        return issued

    async def issue_password_reset(self, actor: Actor, *, user_id: str) -> IssuedInvitation:
        self._authz.require(actor, Scope.USER_WRITE)
        user = await self._require_user(user_id)

        if not user.can_use_public_entrance:
            # A reset only replaces the password, and consuming the link writes
            # `password_hash` while `totp_secret` stays NULL — which violates
            # the users check constraint and 500s at consume time. An account
            # that never completed onboarding has nothing to reset; the remedy
            # is a fresh onboarding link, so that is what is required.
            raise UserNotFoundError(detail=f"user {user.id} has not completed onboarding")

        issued = await self._issue(user, InvitationPurpose.PASSWORD_RESET)
        await self._audit.record(actor, "user.password_reset_issued", target=user.id)
        return issued

    async def _require_user(self, user_id: str) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise UserNotFoundError(detail=f"no user {user_id}")
        return user

    async def _issue(self, user: User, purpose: InvitationPurpose) -> IssuedInvitation:
        # Issuing a new link kills any earlier one of the same purpose. Without
        # this, a link that was intercepted stays usable after the real
        # recipient asks for another.
        await self._invitations.invalidate_outstanding(user.id, purpose)

        token = self._tokens.issue_token()
        expires_at = self._clock.now() + self._ttl
        invitation_id = str(uuid.uuid4())
        await self._invitations.save(
            Invitation(
                id=invitation_id,
                user_id=user.id,
                token_hash=token.hashed,
                purpose=purpose,
                expires_at=expires_at,
            )
        )
        return IssuedInvitation(
            invitation_id=invitation_id,
            user=user,
            token=token.plaintext,
            expires_at=expires_at,
            purpose=purpose,
        )
