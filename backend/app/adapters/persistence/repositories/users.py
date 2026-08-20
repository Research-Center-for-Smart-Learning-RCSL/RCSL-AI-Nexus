"""Postgres users repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    UserRow,
)
from app.domain.entities.actor import Role
from app.domain.entities.user import User

from .shared import _TenantScoped


class PostgresUserRepository(_TenantScoped):
    async def get(self, user_id: str) -> User | None:
        # A select rather than `session.get`, so the tenant filter can be added.
        # Unscoped on the session-resolution path (the tenant is read from the
        # row); scoped for management, so an admin cannot fetch another tenant's
        # user by id.
        row = await self._session.scalar(
            self._scope(select(UserRow).where(UserRow.id == user_id), UserRow.tenant_id)
        )
        return m.user_to_domain(row) if row else None

    async def get_by_login(self, login: str) -> User | None:
        # Deliberately NOT tenant-scoped, even on a scoped repository: `login` is
        # globally unique, so it names one account across the whole platform. The
        # invite flow's duplicate-login check must see that global namespace, or a
        # login already taken in another tenant slips past the check and fails at
        # the unique constraint as a 500 instead of a clean 409. Callers that then
        # act within a tenant use `get(id)`, which is scoped; this only answers
        # "does this login exist anywhere", and the row carries its own tenant.
        row = await self._session.scalar(select(UserRow).where(UserRow.login == login))
        return m.user_to_domain(row) if row else None

    async def get_by_tailscale_login(self, login: str) -> User | None:
        row = await self._session.scalar(
            self._scope(select(UserRow).where(UserRow.tailscale_login == login), UserRow.tenant_id)
        )
        return m.user_to_domain(row) if row else None

    async def list_all(self) -> list[User]:
        rows = (
            await self._session.scalars(
                self._scope(select(UserRow).order_by(UserRow.login), UserRow.tenant_id)
            )
        ).all()
        return [m.user_to_domain(r) for r in rows]

    async def display_names(self) -> dict[str, str]:
        rows = await self._session.execute(
            self._scope(select(UserRow.id, UserRow.display_name), UserRow.tenant_id)
        )
        return {user_id: name for user_id, name in rows}

    async def count(self) -> int:
        """Backs the bootstrap guard: BOOTSTRAP_ADMIN_LOGIN is inert once any
        user exists, so this must count every row platform-wide, which is why
        bootstrap uses an unscoped repository. When scoped it counts one tenant."""
        return int(
            await self._session.scalar(
                self._scope(select(func.count()).select_from(UserRow), UserRow.tenant_id)
            )
            or 0
        )

    async def save(self, user: User) -> None:
        """Full-row upsert. The caller must pass a complete entity.

        `merge` copies every column present on the object, and the mapper sets
        all of them, including the Nones. So saving a partially built User
        blanks whatever it omitted: a `password_hash` of None overwrites a real
        hash, and the victim then cannot sign in and gets an error
        indistinguishable from a wrong password. Read, `replace`, save.

        For the two fields where a concurrent writer is realistic, use the
        conditional updates below instead of this.

        Flushes, for the reason given in the module docstring.
        """
        row = m.user_to_row(user)
        if self._tenant_id is not None:
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def insert_if_absent(self, user: User) -> User:
        """Atomic claim on a login, for the first-admin bootstrap.

        `ON CONFLICT DO NOTHING` rather than a read-then-write: a browser's
        first page load fires several requests concurrently, every one of them
        sees an empty `users` table, and every one of them tries to create the
        same account. Postgres blocks the losers on the conflicting key until
        the winner commits, so the SELECT below then sees the committed row.

        Bootstrap runs unscoped, so the user's own `tenant_id` (the default
        tenant) is what lands.
        """
        values = m.user_to_row_values(user)
        if self._tenant_id is not None:
            values["tenant_id"] = self._tenant_id
        stmt = (
            pg_insert(UserRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[UserRow.login])
        )
        await self._session.execute(stmt)

        row = await self._session.scalar(select(UserRow).where(UserRow.login == user.login))
        if row is None:
            # Only reachable if the row was deleted between the insert and the
            # read. Raising beats returning the entity that was not persisted,
            # which would hand the caller an id no foreign key can reference.
            raise RuntimeError(f"user {user.login} vanished during bootstrap insert")
        return m.user_to_domain(row)

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        """Claim a TOTP counter, or return False if it is not newer.

        Replay prevention cannot be a Python comparison against a value read
        earlier and then written back with `merge`: two requests carrying the
        same code both read the old counter, both pass the check, and both get
        a session. The comparison has to happen in the UPDATE.
        """
        result = await self._session.execute(
            self._scope(
                update(UserRow)
                .where(
                    UserRow.id == user_id,
                    or_(UserRow.totp_last_counter.is_(None), UserRow.totp_last_counter < counter),
                )
                .values(totp_last_counter=counter),
                UserRow.tenant_id,
            )
        )
        # SQLAlchemy types async execute() as Result, which has no rowcount;
        # an UPDATE returns a CursorResult, which does. The cast is the stub gap,
        # not a runtime one.
        return cast("CursorResult[Any]", result).rowcount == 1

    async def set_disabled(self, user_id: str, at: datetime | None) -> None:
        """Targeted update, so disabling an account cannot be undone by a
        login that read the row a moment earlier and saved it back whole."""
        await self._session.execute(
            self._scope(
                update(UserRow).where(UserRow.id == user_id).values(disabled_at=at),
                UserRow.tenant_id,
            )
        )

    async def update_profile(self, user_id: str, *, display_name: str, role: str) -> None:
        """Targeted, for the same reason `set_disabled` is.

        The administrator edit form reads a user, changes a field, and would
        otherwise save the whole row back — reverting a `disabled_at` or a
        `totp_last_counter` that a concurrent disable or login had advanced in
        between. This writes only the two columns the form owns, so those
        conditional updates cannot be undone by it.
        """
        await self._session.execute(
            self._scope(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(display_name=display_name, role=role),
                UserRow.tenant_id,
            )
        )

    async def set_debug_logging_until(self, user_id: str, until: datetime | None) -> bool:
        """Targeted and conditional, the same shape as `advance_totp_counter`.

        `disabled_at IS NULL` belongs in the UPDATE rather than in a check
        before it: a disable landing in between would otherwise leave the
        window open on an account that can no longer sign in, and the caller
        would be told it had been set. Returns False so the use case can say
        which of the two happened.
        """
        result = await self._session.execute(
            self._scope(
                update(UserRow)
                .where(UserRow.id == user_id, UserRow.disabled_at.is_(None))
                .values(debug_logging_until=until),
                UserRow.tenant_id,
            )
        )
        return (result.rowcount or 0) == 1  # type: ignore[attr-defined]

    async def delete(self, user_id: str) -> None:
        await self._session.execute(
            self._scope(delete(UserRow).where(UserRow.id == user_id), UserRow.tenant_id)
        )

    async def count_admins(self) -> int:
        """Counts enabled administrators only. A disabled one cannot sign in,
        so treating them as cover for the last-admin guard would leave an
        instance nobody can manage. Scoped, so the guard keeps every tenant with
        at least one administrator of its own."""
        return int(
            await self._session.scalar(
                self._scope(
                    select(func.count())
                    .select_from(UserRow)
                    .where(UserRow.role == Role.ADMIN.value, UserRow.disabled_at.is_(None)),
                    UserRow.tenant_id,
                )
            )
            or 0
        )
