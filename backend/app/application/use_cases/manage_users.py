"""Editing and removing accounts.

Two guards here exist because their absence is unrecoverable rather than
merely wrong.

**Nobody can remove or demote themselves.** The frontend had this check once
and it never fired, because it compared a UUID against a login. Doing it here
means no caller has to remember it.

**The last enabled administrator is protected.** Removing them leaves an
instance nobody can manage, and the bootstrap setting does not come back: it
is inert the moment any user row exists. Recovering would mean editing the
database by hand.

See docs/architecture/security.md section 5.2.
"""

from __future__ import annotations

from dataclasses import replace

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.user import User
from app.domain.exceptions import (
    LastAdministratorError,
    NotAuthorizedError,
    UserNotFoundError,
)
from app.domain.ports.repositories import (
    ApiKeyRepositoryPort,
    InvitationRepositoryPort,
    UserRepositoryPort,
)
from app.domain.ports.security_ports import AuditPort, AuthorizationPort, SessionRegistryPort
from app.shared.clock import Clock


class ManageUsers:
    def __init__(
        self,
        users: UserRepositoryPort,
        keys: ApiKeyRepositoryPort,
        invitations: InvitationRepositoryPort,
        sessions: SessionRegistryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._keys = keys
        self._invitations = invitations
        self._sessions = sessions
        self._authz = authz
        self._audit = audit
        self._clock = clock

    async def list_all(self, actor: Actor) -> list[User]:
        self._authz.require(actor, Scope.USER_READ)
        return await self._users.list_all()

    async def update(
        self,
        actor: Actor,
        user_id: str,
        *,
        display_name: str | None = None,
        role: Role | None = None,
    ) -> User:
        self._authz.require(actor, Scope.USER_WRITE)
        user = await self._require(user_id)

        if role is not None and role is not user.role:
            if user.id == actor.id:
                # Demoting yourself is almost always a misclick, and on a
                # single-administrator instance it is unrecoverable.
                raise NotAuthorizedError(detail="an administrator cannot change their own role")
            if user.role is Role.ADMIN:
                await self._assert_not_last_admin(user)

        updated = replace(
            user,
            display_name=display_name.strip() if display_name is not None else user.display_name,
            role=role if role is not None else user.role,
        )
        # Targeted update of only the two columns this form owns. A full-row
        # save would write back the `disabled_at` and `totp_last_counter` it
        # read, reverting a concurrent disable or a just-advanced TOTP counter.
        await self._users.update_profile(
            user.id, display_name=updated.display_name, role=updated.role.value
        )

        if role is not None and role is not user.role:
            # Scopes are derived from the role at request time, so a live
            # session would otherwise keep whatever it was granted at login
            # until it expired.
            await self._sessions.invalidate_all(user.id, self._clock.now())
            await self._audit.record(
                actor, "user.role_changed", target=user.id, detail={"role": updated.role.value}
            )
        else:
            await self._audit.record(actor, "user.updated", target=user.id)

        return updated

    async def set_disabled(self, actor: Actor, user_id: str, *, disabled: bool) -> User:
        """Preferred over deletion: it ends access immediately while leaving
        the account's usage records attributable."""
        self._authz.require(actor, Scope.USER_WRITE)
        user = await self._require(user_id)

        if disabled:
            if user.id == actor.id:
                raise NotAuthorizedError(detail="an administrator cannot disable themselves")
            if user.role is Role.ADMIN:
                await self._assert_not_last_admin(user)

        now = self._clock.now()
        await self._users.set_disabled(user.id, now if disabled else None)

        if disabled:
            # Every live session dies now rather than at its own expiry.
            await self._sessions.invalidate_all(user.id, now)

        await self._audit.record(
            actor, "user.disabled" if disabled else "user.enabled", target=user.id
        )
        return replace(user, disabled_at=now if disabled else None)

    async def delete(self, actor: Actor, user_id: str) -> None:
        """Removes the account and everything that references it.

        `api_keys`, `invitations` and `recovery_codes` all carry a foreign key
        to `users`, so they go first or the delete is impossible. Their keys
        stopping immediately is the correct consequence, not a side effect:
        an account that no longer exists should not still be issuing requests.

        `usage_records` and `audit_log` hold the id as a plain column with no
        foreign key, deliberately. They outlive the account, which is what
        makes the audit trail worth keeping.
        """
        self._authz.require(actor, Scope.USER_WRITE)
        user = await self._require(user_id)

        if user.id == actor.id:
            raise NotAuthorizedError(detail="an administrator cannot delete themselves")
        if user.role is Role.ADMIN:
            await self._assert_not_last_admin(user)

        await self._sessions.invalidate_all(user.id, self._clock.now())
        await self._keys.delete_for_owner(user.id)
        await self._invitations.delete_for_user(user.id)
        await self._users.delete(user.id)

        await self._audit.record(
            actor, "user.deleted", target=user.id, detail={"login": user.login}
        )

    async def _assert_not_last_admin(self, user: User) -> None:
        if user.disabled_at is not None:
            # Already excluded from the count, so removing them changes
            # nothing about who can manage the instance.
            return
        if await self._users.count_admins() <= 1:
            raise LastAdministratorError(detail=f"user {user.id} is the only enabled admin")

    async def _require(self, user_id: str) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise UserNotFoundError(detail=f"no user {user_id}")
        return user
