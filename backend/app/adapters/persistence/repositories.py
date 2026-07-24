"""Postgres implementations of the repository ports.

Grouped in one module because they share a session and a shape, and splitting
them across seven files would mostly duplicate imports.

None of these commit. `session_scope` in infrastructure/db.py owns the
transaction, so a use case touching several repositories either lands entirely
or not at all.

**Every `save` flushes, and that is load-bearing rather than tidiness.** These
ORM models declare foreign key columns but no `relationship()`, so
SQLAlchemy's unit of work has no dependency graph to order a flush by; with
`autoflush=False` — which production uses deliberately — it falls back to
alphabetical order by table name, which puts `api_keys`, `invitations`,
`models` and `recovery_codes` *before* the `users` and `nodes` rows they
reference. Writing a parent and a child in one transaction therefore failed on
the foreign key. Flushing at each write makes the order the caller's order.

It also means a constraint violation is raised where the call was made rather
than at commit, which in FastAPI happens *after* the response has been sent
and has nowhere left to report. And it is what lets a use case read back a
row it has just written to pick up a server-assigned default.

`UsageRepository.record` is the deliberate exception: it has no foreign key,
and it sits on the streaming hot path where an extra round trip per request
is not worth buying nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    ApiKeyRow,
    InvitationRow,
    ModelRow,
    NodeRow,
    RecoveryCodeRow,
    RoutingPolicyRow,
    UsageRecordRow,
    UserRow,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.usage import UsageRecord
from app.domain.entities.user import User


class _Base:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class PostgresNodeRepository(_Base):
    async def get(self, node_id: str) -> Node | None:
        row = await self._session.get(NodeRow, node_id)
        return m.node_to_domain(row) if row else None

    async def list_all(self) -> list[Node]:
        rows = (await self._session.scalars(select(NodeRow))).all()
        return [m.node_to_domain(r) for r in rows]

    async def save(self, node: Node) -> None:
        await self._session.merge(m.node_to_row(node))
        await self._session.flush()


class PostgresModelRepository(_Base):
    async def get(self, model_id: str) -> Model | None:
        row = await self._session.get(ModelRow, model_id)
        return m.model_to_domain(row) if row else None

    async def get_by_alias(self, alias: str) -> Model | None:
        row = await self._session.scalar(select(ModelRow).where(ModelRow.alias == alias))
        return m.model_to_domain(row) if row else None

    async def list_all(self) -> list[Model]:
        rows = (await self._session.scalars(select(ModelRow))).all()
        return [m.model_to_domain(r) for r in rows]

    async def list_loaded(self, node_id: str) -> list[Model]:
        rows = (
            await self._session.scalars(
                select(ModelRow).where(
                    ModelRow.node_id == node_id,
                    ModelRow.state == ModelState.LOADED.value,
                )
            )
        ).all()
        return [m.model_to_domain(r) for r in rows]

    async def list_occupying_memory(self, node_id: str) -> list[Model]:
        rows = (
            await self._session.scalars(
                select(ModelRow).where(
                    ModelRow.node_id == node_id,
                    ModelRow.state.in_((ModelState.LOADED.value, ModelState.LOADING.value)),
                )
            )
        ).all()
        return [m.model_to_domain(r) for r in rows]

    async def save(self, model: Model) -> None:
        await self._session.merge(m.model_to_row(model))
        await self._session.flush()

    async def set_state(self, model_id: str, state: ModelState) -> None:
        await self._session.execute(
            update(ModelRow).where(ModelRow.id == model_id).values(state=state.value)
        )

    async def delete(self, model_id: str) -> None:
        await self._session.execute(delete(ModelRow).where(ModelRow.id == model_id))

    async def reconcile_transient_states(self, mapping: dict[ModelState, ModelState]) -> int:
        """One UPDATE per transient state. A CASE would be terser but this
        reports the count per source state, which is what an operator wants in
        the log after a crash."""
        total = 0
        for source, target in mapping.items():
            result = await self._session.execute(
                update(ModelRow).where(ModelRow.state == source.value).values(state=target.value)
            )
            total += result.rowcount or 0  # type: ignore[attr-defined]
        return total


class PostgresRoutingPolicyRepository(_Base):
    async def get(self, capability: str) -> RoutingPolicy | None:
        row = await self._session.get(RoutingPolicyRow, capability)
        return m.routing_policy_to_domain(row) if row else None

    async def list_all(self) -> list[RoutingPolicy]:
        rows = (await self._session.scalars(select(RoutingPolicyRow))).all()
        return [m.routing_policy_to_domain(r) for r in rows]

    async def save(self, policy: RoutingPolicy) -> None:
        await self._session.merge(m.routing_policy_to_row(policy))
        await self._session.flush()

    async def delete(self, capability: str) -> None:
        await self._session.execute(
            delete(RoutingPolicyRow).where(RoutingPolicyRow.capability == capability)
        )


class PostgresApiKeyRepository(_Base):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None:
        row = await self._session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_id == key_id))
        return m.api_key_to_domain(row) if row else None

    async def list_for_owner(self, owner_id: str) -> list[ApiKey]:
        rows = (
            await self._session.scalars(select(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id))
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def list_all(self) -> list[ApiKey]:
        rows = (
            await self._session.scalars(select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc()))
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def save(self, key: ApiKey) -> None:
        await self._session.merge(m.api_key_to_row(key))
        await self._session.flush()

    async def delete_for_owner(self, owner_id: str) -> None:
        await self._session.execute(delete(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id))

    async def revoke(self, key_id: str, at: datetime) -> None:
        # Only the first revocation writes a timestamp. Without the guard a
        # repeated call moves the recorded time forward, so "when was this
        # revoked" answers with the most recent attempt rather than the moment
        # it stopped working.
        await self._session.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        """Targeted update of the editable columns, refused if revoked.

        A full-row `save` of a read-then-modified entity would write back
        `revoked_at` from the value it read, so an edit racing a concurrent
        `revoke` rerevived the key by overwriting the revocation with the NULL
        it had loaded. This touches only the named columns and requires
        `revoked_at IS NULL`, so it cannot revert a revocation and returns
        False if one landed first.
        """
        result = await self._session.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
            .values(**values)
        )
        return (result.rowcount or 0) == 1  # type: ignore[attr-defined]


class PostgresUserRepository(_Base):
    async def get(self, user_id: str) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return m.user_to_domain(row) if row else None

    async def get_by_login(self, login: str) -> User | None:
        row = await self._session.scalar(select(UserRow).where(UserRow.login == login))
        return m.user_to_domain(row) if row else None

    async def get_by_tailscale_login(self, login: str) -> User | None:
        row = await self._session.scalar(select(UserRow).where(UserRow.tailscale_login == login))
        return m.user_to_domain(row) if row else None

    async def list_all(self) -> list[User]:
        rows = (await self._session.scalars(select(UserRow).order_by(UserRow.login))).all()
        return [m.user_to_domain(r) for r in rows]

    async def display_names(self) -> dict[str, str]:
        rows = await self._session.execute(select(UserRow.id, UserRow.display_name))
        return {user_id: name for user_id, name in rows}

    async def count(self) -> int:
        """Backs the bootstrap guard: BOOTSTRAP_ADMIN_LOGIN is inert once any
        user exists, so this must count every row, not only enabled ones."""
        return int(await self._session.scalar(select(func.count()).select_from(UserRow)) or 0)

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
        await self._session.merge(m.user_to_row(user))
        await self._session.flush()

    async def insert_if_absent(self, user: User) -> User:
        """Atomic claim on a login, for the first-admin bootstrap.

        `ON CONFLICT DO NOTHING` rather than a read-then-write: a browser's
        first page load fires several requests concurrently, every one of them
        sees an empty `users` table, and every one of them tries to create the
        same account. Postgres blocks the losers on the conflicting key until
        the winner commits, so the SELECT below then sees the committed row.
        """
        stmt = (
            pg_insert(UserRow)
            .values(**m.user_to_row_values(user))
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
            update(UserRow)
            .where(
                UserRow.id == user_id,
                or_(UserRow.totp_last_counter.is_(None), UserRow.totp_last_counter < counter),
            )
            .values(totp_last_counter=counter)
        )
        return result.rowcount == 1

    async def set_disabled(self, user_id: str, at: datetime | None) -> None:
        """Targeted update, so disabling an account cannot be undone by a
        login that read the row a moment earlier and saved it back whole."""
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(disabled_at=at)
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
            update(UserRow)
            .where(UserRow.id == user_id)
            .values(display_name=display_name, role=role)
        )

    async def delete(self, user_id: str) -> None:
        await self._session.execute(delete(UserRow).where(UserRow.id == user_id))

    async def count_admins(self) -> int:
        """Counts enabled administrators only. A disabled one cannot sign in,
        so treating them as cover for the last-admin guard would leave an
        instance nobody can manage."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(UserRow)
                .where(UserRow.role == Role.ADMIN.value, UserRow.disabled_at.is_(None))
            )
            or 0
        )


class PostgresInvitationRepository(_Base):
    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        row = await self._session.scalar(
            select(InvitationRow).where(InvitationRow.token_hash == token_hash)
        )
        return m.invitation_to_domain(row) if row else None

    async def save(self, invitation: Invitation) -> None:
        await self._session.merge(m.invitation_to_row(invitation))
        await self._session.flush()

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        """Claim the invitation. Returns False if someone else already did.

        The `WHERE consumed_at IS NULL` makes the claim atomic, but the result
        has to be inspected for that to mean anything. Discarding it left both
        racers believing they had consumed the link, which is exactly the
        interception scenario the single-use rule exists for.
        """
        result = await self._session.execute(
            update(InvitationRow)
            .where(InvitationRow.id == invitation_id, InvitationRow.consumed_at.is_(None))
            .values(consumed_at=at)
        )
        return result.rowcount == 1

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None:
        """Issuing a new link kills any earlier one.

        Without this, a reset link that was intercepted stays usable after the
        real user asks for another.
        """
        await self._session.execute(
            delete(InvitationRow).where(
                InvitationRow.user_id == user_id,
                InvitationRow.purpose == purpose.value,
                InvitationRow.consumed_at.is_(None),
            )
        )

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None:
        self._session.add_all([m.recovery_code_to_row(c) for c in codes])
        await self._session.flush()

    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]:
        rows = (
            await self._session.scalars(
                select(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
            )
        ).all()
        return [m.recovery_code_to_domain(r) for r in rows]

    async def delete_recovery_codes(self, user_id: str) -> None:
        await self._session.execute(
            delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
        )

    async def delete_for_user(self, user_id: str) -> None:
        await self._session.execute(
            delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
        )
        await self._session.execute(delete(InvitationRow).where(InvitationRow.user_id == user_id))

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool:
        """Same atomic claim, and the same reason to check it. A recovery code
        bypasses the second factor, so a code that can be redeemed twice is
        worse than an invitation that can."""
        result = await self._session.execute(
            update(RecoveryCodeRow)
            .where(RecoveryCodeRow.id == code_id, RecoveryCodeRow.used_at.is_(None))
            .values(used_at=at)
        )
        return result.rowcount == 1


class PostgresUsageRepository(_Base):
    async def record(self, usage: UsageRecord) -> None:
        self._session.add(m.usage_to_row(usage))

    async def tokens_used_today(self, api_key_id: str) -> int:
        since = datetime.now(UTC) - timedelta(days=1)
        total = await self._session.scalar(
            select(func.coalesce(func.sum(UsageRecordRow.tokens), 0)).where(
                UsageRecordRow.api_key_id == api_key_id,
                UsageRecordRow.at >= since,
            )
        )
        return int(total or 0)

    async def last_used_by_key(self) -> dict[str, datetime]:
        """One aggregate for every key, not one query per key.

        `api_keys` has no `last_used_at` column on purpose: writing it would
        mean the gateway updating that table on every request, and the account
        split in security.md section 6 exists precisely so a compromised
        gateway cannot write there. The same fact is already in this table,
        under the index `ix_usage_key_at`.
        """
        rows = await self._session.execute(
            select(UsageRecordRow.api_key_id, func.max(UsageRecordRow.at))
            .where(UsageRecordRow.api_key_id.is_not(None))
            .group_by(UsageRecordRow.api_key_id)
        )
        return {key_id: at for key_id, at in rows if key_id is not None}

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(UsageRecordRow.tokens), 0),
                ).where(UsageRecordRow.at >= since)
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)
