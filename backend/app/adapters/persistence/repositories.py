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
from typing import Any, Self, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    ApiKeyRow,
    AuditLogRow,
    InvitationRow,
    KnowledgeCollectionRow,
    KnowledgeDocumentRow,
    ModelRow,
    NodeRow,
    RecoveryCodeRow,
    RoutingPolicyRow,
    TenantRow,
    UsageRecordRow,
    UserRow,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.audit import AuditEntry
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.knowledge import (
    TRANSIENT_DOCUMENT_STATES,
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord
from app.domain.entities.user import User


class _Base:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class _TenantScoped:
    """A repository whose reads filter and whose writes stamp `tenant_id`.

    The filter lives here, in the adapter, and is taken from the tenant this
    repository was constructed with, never from a caller, so a use case cannot
    read or write another tenant's rows and cannot forget to say which tenant it
    means. The di builders construct these with the actor's tenant, so the wiring
    is the only place that decides. See docs/architecture/security.md section 7.3.

    `unscoped` builds one with no tenant, for the identity and bootstrap paths
    only: they resolve a principal (by session id, login, or key handle) before
    any tenant is known, and reading exactly the one row a unique handle names is
    not a cross-tenant enumeration. Every other construction passes a real tenant.
    """

    def __init__(self, session: AsyncSession, tenant_id: str | None) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @classmethod
    def unscoped(cls, session: AsyncSession) -> Self:
        return cls(session, None)

    def _scope(self, stmt: Any, column: Any) -> Any:
        """Add `column == tenant` unless this is an unscoped repository."""
        if self._tenant_id is None:
            return stmt
        return stmt.where(column == self._tenant_id)


class PostgresTenantRepository(_Base):
    """Platform-global, like nodes and models: tenants are not themselves
    tenant-scoped, and managing them is an admin operation."""

    async def get(self, tenant_id: str) -> Tenant | None:
        row = await self._session.get(TenantRow, tenant_id)
        return m.tenant_to_domain(row) if row else None

    async def get_by_name(self, name: str) -> Tenant | None:
        row = await self._session.scalar(select(TenantRow).where(TenantRow.name == name))
        return m.tenant_to_domain(row) if row else None

    async def list_all(self) -> list[Tenant]:
        rows = (await self._session.scalars(select(TenantRow).order_by(TenantRow.name))).all()
        return [m.tenant_to_domain(r) for r in rows]

    async def save(self, tenant: Tenant) -> None:
        await self._session.merge(m.tenant_to_row(tenant))
        await self._session.flush()


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

    async def set_status(self, node_id: str, status: NodeStatus) -> None:
        await self._session.execute(
            update(NodeRow).where(NodeRow.id == node_id).values(status=status.value)
        )

    async def delete(self, node_id: str) -> None:
        await self._session.execute(delete(NodeRow).where(NodeRow.id == node_id))


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
        # Intent says LOADED or LOADING, or the heartbeat observed the weights
        # resident regardless of what intent says: a model someone warmed with
        # an out-of-band `ollama run` occupies memory the budget must count,
        # even though no registry operation ever claimed it.
        rows = (
            await self._session.scalars(
                select(ModelRow).where(
                    ModelRow.node_id == node_id,
                    or_(
                        ModelRow.state.in_((ModelState.LOADED.value, ModelState.LOADING.value)),
                        ModelRow.observed_state == ModelState.LOADED.value,
                    ),
                )
            )
        ).all()
        return [m.model_to_domain(r) for r in rows]

    async def save(self, model: Model) -> None:
        await self._session.merge(m.model_to_row(model))
        await self._session.flush()

    async def set_state(self, model_id: str, state: ModelState) -> None:
        # The observation is cleared with the intent write, because it now
        # predates it. Readers rank observation over intent, so a load that has
        # just succeeded would otherwise be overruled for up to a heartbeat
        # interval by the sweep's earlier `downloaded` — routing would skip the
        # model the operator just loaded and a `model_state: [loaded]` policy
        # with one candidate would answer 503. Null is the honest value until
        # the next sweep looks: "not currently observed", which sends every
        # reader back to intent.
        await self._session.execute(
            update(ModelRow)
            .where(ModelRow.id == model_id)
            .values(
                state=state.value,
                observed_state=None,
                observed_memory_gb=None,
                observed_at=None,
            )
        )

    async def set_observed(
        self, model_id: str, state: ModelState | None, memory_gb: float | None
    ) -> None:
        # The timestamp is the database's now(), not a client clock, and it is
        # cleared alongside a None state: all three columns null together means
        # "not currently observed", which is also the migration's start state.
        await self._session.execute(
            update(ModelRow)
            .where(ModelRow.id == model_id)
            .values(
                observed_state=state.value if state else None,
                observed_memory_gb=memory_gb,
                observed_at=func.now() if state else None,
            )
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


class PostgresApiKeyRepository(_TenantScoped):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None:
        # Unscoped on the gateway's authentication path (the tenant is not known
        # until the key is found); scoped for management, so an admin cannot
        # reach another tenant's key by its handle.
        row = await self._session.scalar(
            self._scope(select(ApiKeyRow).where(ApiKeyRow.key_id == key_id), ApiKeyRow.tenant_id)
        )
        return m.api_key_to_domain(row) if row else None

    async def list_for_owner(self, owner_id: str) -> list[ApiKey]:
        rows = (
            await self._session.scalars(
                self._scope(
                    select(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id), ApiKeyRow.tenant_id
                )
            )
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def list_all(self) -> list[ApiKey]:
        rows = (
            await self._session.scalars(
                self._scope(
                    select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc()), ApiKeyRow.tenant_id
                )
            )
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def save(self, key: ApiKey) -> None:
        row = m.api_key_to_row(key)
        if self._tenant_id is not None:
            # Stamp rather than trust the entity, so a new key lands in this
            # repository's tenant regardless of what the use case set.
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def delete_for_owner(self, owner_id: str) -> None:
        await self._session.execute(
            self._scope(
                delete(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id), ApiKeyRow.tenant_id
            )
        )

    async def revoke(self, key_id: str, at: datetime) -> None:
        # Only the first revocation writes a timestamp. Without the guard a
        # repeated call moves the recorded time forward, so "when was this
        # revoked" answers with the most recent attempt rather than the moment
        # it stopped working.
        await self._session.execute(
            self._scope(
                update(ApiKeyRow)
                .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
                .values(revoked_at=at),
                ApiKeyRow.tenant_id,
            )
        )

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        """Targeted update of the editable columns, refused if revoked.

        A full-row `save` of a read-then-modified entity would write back
        `revoked_at` from the value it read, so an edit racing a concurrent
        `revoke` rerevived the key by overwriting the revocation with the NULL
        it had loaded. This touches only the named columns and requires
        `revoked_at IS NULL`, so it cannot revert a revocation and returns
        False if one landed first. The tenant scope means an admin cannot edit
        another tenant's key even by its handle.
        """
        result = await self._session.execute(
            self._scope(
                update(ApiKeyRow)
                .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
                .values(**values),
                ApiKeyRow.tenant_id,
            )
        )
        return (result.rowcount or 0) == 1  # type: ignore[attr-defined]


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
        # SQLAlchemy types async execute() as Result, which has no rowcount;
        # an UPDATE returns a CursorResult, which does. The cast is the stub gap,
        # not a runtime one.
        return cast("CursorResult[Any]", result).rowcount == 1

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
        # SQLAlchemy types async execute() as Result, which has no rowcount;
        # an UPDATE returns a CursorResult, which does. The cast is the stub gap,
        # not a runtime one.
        return cast("CursorResult[Any]", result).rowcount == 1


class PostgresUsageRepository(_TenantScoped):
    async def record(self, usage: UsageRecord) -> None:
        row = m.usage_to_row(usage)
        if self._tenant_id is not None:
            # Stamp from the gateway's scoped repository, so usage lands under
            # the tenant of the key that produced it regardless of the entity.
            row.tenant_id = self._tenant_id
        self._session.add(row)

    async def tokens_used_today(self, api_key_id: str) -> int:
        # Both halves. `quota_tokens_per_day` charged for generated tokens
        # alone until 2026-08-04, so a caller could fill the context window on
        # every request and spend none of its quota doing it — on this
        # hardware, prompt evaluation is most of the wait.
        since = datetime.now(UTC) - timedelta(days=1)
        total = await self._session.scalar(
            self._scope(
                select(
                    func.coalesce(func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0)
                ).where(
                    UsageRecordRow.api_key_id == api_key_id,
                    UsageRecordRow.at >= since,
                ),
                UsageRecordRow.tenant_id,
            )
        )
        return int(total or 0)

    async def last_used_by_key(self) -> dict[str, datetime]:
        """One aggregate for every key, not one query per key.

        `api_keys` has no `last_used_at` column on purpose: writing it would
        mean the gateway updating that table on every request, and the account
        split in security.md section 6 exists precisely so a compromised
        gateway cannot write there. The same fact is already in this table,
        under the index `ix_usage_key_at`. Scoped, so a tenant's dashboard sees
        only its own keys' activity.
        """
        rows = await self._session.execute(
            self._scope(
                select(UsageRecordRow.api_key_id, func.max(UsageRecordRow.at))
                .where(UsageRecordRow.api_key_id.is_not(None))
                .group_by(UsageRecordRow.api_key_id),
                UsageRecordRow.tenant_id,
            )
        )
        return {key_id: at for key_id, at in rows if key_id is not None}

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        row = (
            await self._session.execute(
                self._scope(
                    select(
                        func.count(),
                        # Both halves, matching the quota: a dashboard that
                        # counted only output would disagree with the number
                        # the caller is actually charged.
                        func.coalesce(
                            func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0
                        ),
                    ).where(UsageRecordRow.at >= since),
                    UsageRecordRow.tenant_id,
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    async def bucketed_usage(
        self,
        since: datetime,
        until: datetime,
        unit: BucketUnit,
        *,
        actor_id: str | None = None,
    ) -> list[UsageBucket]:
        # `unit` reaches date_trunc as a bind parameter, not interpolated text,
        # and the use case restricts it to the BucketUnit literals regardless.
        bucket = func.date_trunc(unit, UsageRecordRow.at)
        where = [UsageRecordRow.at >= since, UsageRecordRow.at < until]
        # Narrowed *inside* `_scope`, never instead of it: one account's usage is
        # still read within its tenant's boundary, so an actor id that belonged
        # to another tenant would select nothing rather than crossing it.
        if actor_id is not None:
            where.append(UsageRecordRow.actor_id == actor_id)
        rows = await self._session.execute(
            self._scope(
                select(
                    bucket.label("bucket"),
                    UsageRecordRow.capability,
                    func.count(),
                    # Both halves, as above, so the chart and the quota agree.
                    func.coalesce(
                        func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0
                    ),
                )
                .where(*where)
                .group_by(bucket, UsageRecordRow.capability)
                .order_by(bucket),
                UsageRecordRow.tenant_id,
            )
        )
        return [
            UsageBucket(
                bucket_start=start,
                capability=capability,
                requests=int(requests or 0),
                tokens=int(tokens or 0),
            )
            for start, capability, requests, tokens in rows
        ]


class PostgresKnowledgeRepository(_TenantScoped):
    """Collections and documents.

    Both tables carry `tenant_id` and both are filtered on it directly rather
    than a document being scoped through its collection. The redundancy is the
    point: a document read is correctly scoped without a join, so there is no
    query shape in which forgetting the join silently widens the boundary.
    """

    # --- collections -----------------------------------------------------

    async def get_collection(self, collection_id: str) -> KnowledgeCollection | None:
        stmt = self._scope(
            select(KnowledgeCollectionRow).where(KnowledgeCollectionRow.id == collection_id),
            KnowledgeCollectionRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return m.collection_to_domain(row, await self.count_documents(collection_id=row.id))

    async def get_collection_by_name(self, name: str) -> KnowledgeCollection | None:
        stmt = self._scope(
            select(KnowledgeCollectionRow).where(KnowledgeCollectionRow.name == name),
            KnowledgeCollectionRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.collection_to_domain(row) if row else None

    async def list_collections(self) -> list[KnowledgeCollection]:
        # One grouped count for every collection rather than a query per row:
        # the listing renders a document count beside each name.
        rows_by_collection = await self._session.execute(
            self._scope(
                select(KnowledgeDocumentRow.collection_id, func.count()).group_by(
                    KnowledgeDocumentRow.collection_id
                ),
                KnowledgeDocumentRow.tenant_id,
            )
        )
        counts: dict[str, int] = {
            str(collection_id): int(count) for collection_id, count in rows_by_collection.all()
        }
        stmt = self._scope(
            select(KnowledgeCollectionRow).order_by(KnowledgeCollectionRow.name),
            KnowledgeCollectionRow.tenant_id,
        )
        rows = (await self._session.scalars(stmt)).all()
        return [m.collection_to_domain(r, counts.get(r.id, 0)) for r in rows]

    async def save_collection(self, collection: KnowledgeCollection) -> None:
        row = m.collection_to_row(collection)
        if self._tenant_id is not None:
            # Stamp rather than trust the entity, as every scoped write here does.
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def delete_collection(self, collection_id: str) -> None:
        stmt = self._scope(
            delete(KnowledgeCollectionRow).where(KnowledgeCollectionRow.id == collection_id),
            KnowledgeCollectionRow.tenant_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    # --- documents -------------------------------------------------------

    async def get_document(self, document_id: str) -> KnowledgeDocument | None:
        stmt = self._scope(
            select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id == document_id),
            KnowledgeDocumentRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.document_to_domain(row) if row else None

    async def list_documents(
        self, *, collection_id: str | None = None, limit: int, offset: int
    ) -> list[KnowledgeDocument]:
        stmt = self._scope(select(KnowledgeDocumentRow), KnowledgeDocumentRow.tenant_id)
        if collection_id is not None:
            stmt = stmt.where(KnowledgeDocumentRow.collection_id == collection_id)
        # `id` as a tiebreaker, not decoration. `uploaded_at` alone leaves rows
        # sharing a timestamp in no defined order between queries, and offset
        # paging over an unstable order can skip a row. That is a cosmetic
        # glitch in the UI and a real failure in `ManageKnowledge._all_documents`,
        # which pages through this to delete a collection: a skipped document
        # keeps its foreign key, so the delete then fails on the constraint
        # after other documents' bytes and vectors are already gone.
        stmt = (
            stmt.order_by(KnowledgeDocumentRow.uploaded_at.desc(), KnowledgeDocumentRow.id)
            .limit(limit)
            .offset(offset)
        )
        rows = await self._session.scalars(stmt)
        return [m.document_to_domain(row) for row in rows]

    async def count_documents(self, *, collection_id: str | None = None) -> int:
        stmt = self._scope(
            select(func.count()).select_from(KnowledgeDocumentRow),
            KnowledgeDocumentRow.tenant_id,
        )
        if collection_id is not None:
            stmt = stmt.where(KnowledgeDocumentRow.collection_id == collection_id)
        return int(await self._session.scalar(stmt) or 0)

    async def save_document(self, document: KnowledgeDocument) -> None:
        row = m.document_to_row(document)
        if self._tenant_id is not None:
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def set_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        # `error` is always written, cleared to NULL when not supplied: a
        # document that fails, is retried and succeeds must not keep displaying
        # the reason it failed the first time.
        values: dict[str, Any] = {"status": status.value, "error": error}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        stmt = self._scope(
            update(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.id == document_id)
            .values(**values),
            KnowledgeDocumentRow.tenant_id,
        )
        await self._session.execute(stmt)

    async def claim_document_status(
        self, document_id: str, expected: frozenset[DocumentStatus], claimed: DocumentStatus
    ) -> bool:
        # The status predicate is what makes this a claim rather than a write:
        # the row moves only if it is still where the caller found it, so of two
        # concurrent claimers exactly one sees a matching row and the other's
        # UPDATE matches nothing. `rowcount` is the answer, the same way
        # `advance_totp_counter` and `consume` read theirs.
        stmt = self._scope(
            update(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.id == document_id,
                KnowledgeDocumentRow.status.in_([s.value for s in expected]),
            )
            .values(status=claimed.value, error=None),
            KnowledgeDocumentRow.tenant_id,
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return (result.rowcount or 0) > 0
        await self._session.flush()

    async def delete_document(self, document_id: str) -> None:
        stmt = self._scope(
            delete(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id == document_id),
            KnowledgeDocumentRow.tenant_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def reconcile_transient_documents(self, error: str) -> int:
        """Deliberately unscoped by tenant: this runs at deploy, on behalf of no
        caller, and a crash strands rows in every tenant. It is constructed
        unscoped for that reason (infrastructure/provision.py)."""
        result = await self._session.execute(
            update(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.status.in_([s.value for s in TRANSIENT_DOCUMENT_STATES]))
            .values(status=DocumentStatus.ERROR.value, error=error)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount


class PostgresAuditLogRepository(_TenantScoped):
    """Read side of the audit log, tenant-scoped like every other read. The
    write side (`PostgresAudit`) uses its own transaction; this does not, because
    reading is an ordinary request-session query."""

    def _filtered(
        self,
        stmt: Any,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Any:
        stmt = self._scope(stmt, AuditLogRow.tenant_id)
        if action:
            stmt = stmt.where(AuditLogRow.action == action)
        if outcome:
            stmt = stmt.where(AuditLogRow.outcome == outcome)
        if actor_id:
            stmt = stmt.where(AuditLogRow.actor_id == actor_id)
        if since is not None:
            stmt = stmt.where(AuditLogRow.at >= since)
        if until is not None:
            stmt = stmt.where(AuditLogRow.at < until)
        return stmt

    async def list_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[AuditEntry]:
        stmt = self._filtered(
            select(AuditLogRow),
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        # Newest first: an operator reads the most recent action, and the pager
        # walks backwards through history.
        stmt = stmt.order_by(AuditLogRow.at.desc()).limit(limit).offset(offset)
        rows = await self._session.scalars(stmt)
        return [m.audit_row_to_domain(row) for row in rows]

    async def count_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int:
        stmt = self._filtered(
            select(func.count()).select_from(AuditLogRow),
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        total = await self._session.scalar(stmt)
        return int(total or 0)
