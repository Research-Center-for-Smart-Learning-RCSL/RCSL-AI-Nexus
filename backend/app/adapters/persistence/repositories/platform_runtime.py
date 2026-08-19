"""Persistence platform runtime boundary."""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, or_, select, update

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    ModelRow,
    NodeRow,
    RoutingPolicyRow,
    TenantRow,
)
from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant

from .shared import _Base

logger = logging.getLogger(__name__)


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
