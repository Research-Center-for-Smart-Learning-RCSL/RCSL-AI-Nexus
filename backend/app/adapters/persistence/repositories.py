"""Postgres implementations of the repository ports.

Grouped in one module because they share a session and a shape, and splitting
them across seven files would mostly duplicate imports.

None of these commit. `session_scope` in infrastructure/db.py owns the
transaction, so a use case touching several repositories either lands entirely
or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
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

    async def save(self, model: Model) -> None:
        await self._session.merge(m.model_to_row(model))

    async def set_state(self, model_id: str, state: ModelState) -> None:
        await self._session.execute(
            update(ModelRow).where(ModelRow.id == model_id).values(state=state.value)
        )


class PostgresRoutingPolicyRepository(_Base):
    async def get(self, capability: str) -> RoutingPolicy | None:
        row = await self._session.get(RoutingPolicyRow, capability)
        return m.routing_policy_to_domain(row) if row else None

    async def list_all(self) -> list[RoutingPolicy]:
        rows = (await self._session.scalars(select(RoutingPolicyRow))).all()
        return [m.routing_policy_to_domain(r) for r in rows]

    async def save(self, policy: RoutingPolicy) -> None:
        await self._session.merge(m.routing_policy_to_row(policy))


class PostgresApiKeyRepository(_Base):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None:
        row = await self._session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_id == key_id))
        return m.api_key_to_domain(row) if row else None

    async def list_for_owner(self, owner_id: str) -> list[ApiKey]:
        rows = (
            await self._session.scalars(select(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id))
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def save(self, key: ApiKey) -> None:
        await self._session.merge(m.api_key_to_row(key))

    async def revoke(self, key_id: str, at: datetime) -> None:
        await self._session.execute(
            update(ApiKeyRow).where(ApiKeyRow.key_id == key_id).values(revoked_at=at)
        )


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

    async def count(self) -> int:
        """Backs the bootstrap guard: BOOTSTRAP_ADMIN_LOGIN is inert once any
        user exists, so this must count every row, not only enabled ones."""
        return int(await self._session.scalar(select(func.count()).select_from(UserRow)) or 0)

    async def save(self, user: User) -> None:
        await self._session.merge(m.user_to_row(user))


class PostgresInvitationRepository(_Base):
    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        row = await self._session.scalar(
            select(InvitationRow).where(InvitationRow.token_hash == token_hash)
        )
        return m.invitation_to_domain(row) if row else None

    async def save(self, invitation: Invitation) -> None:
        await self._session.merge(m.invitation_to_row(invitation))

    async def consume(self, invitation_id: str, at: datetime) -> None:
        await self._session.execute(
            update(InvitationRow)
            .where(InvitationRow.id == invitation_id, InvitationRow.consumed_at.is_(None))
            .values(consumed_at=at)
        )

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

    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]:
        rows = (
            await self._session.scalars(
                select(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
            )
        ).all()
        return [m.recovery_code_to_domain(r) for r in rows]

    async def consume_recovery_code(self, code_id: str, at: datetime) -> None:
        await self._session.execute(
            update(RecoveryCodeRow)
            .where(RecoveryCodeRow.id == code_id, RecoveryCodeRow.used_at.is_(None))
            .values(used_at=at)
        )


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
