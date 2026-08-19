"""Persistence platform runtime boundary."""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.model import Model, ModelState
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant


class TenantRepositoryPort(Protocol):
    """Platform-global, not tenant-scoped: tenants are the boundary, not data
    inside one."""

    async def get(self, tenant_id: str) -> Tenant | None: ...
    async def get_by_name(self, name: str) -> Tenant | None: ...
    async def list_all(self) -> list[Tenant]: ...
    async def save(self, tenant: Tenant) -> None: ...


class ModelRepositoryPort(Protocol):
    async def get(self, model_id: str) -> Model | None: ...
    async def get_by_alias(self, alias: str) -> Model | None: ...
    async def list_all(self) -> list[Model]: ...
    async def list_loaded(self, node_id: str) -> list[Model]: ...

    async def list_occupying_memory(self, node_id: str) -> list[Model]:
        """Loaded models plus those mid-load. A LOADING model already holds or
        is about to hold its memory, so the budget must count it or two
        concurrent loads each see room the other is taking."""
        ...

    async def save(self, model: Model) -> None: ...

    async def set_state(self, model_id: str, state: ModelState) -> None:
        """Write intent, and clear the observation that now predates it.

        The pairing is the contract, not an implementation detail. Readers rank
        observation over intent, so an observation taken before this transition
        would outrank the transition — a model loaded a second ago would keep
        routing as `downloaded` until the next sweep. Null means "not currently
        observed", which sends every reader back to intent until the heartbeat
        looks again."""
        ...

    async def set_observed(
        self, model_id: str, state: ModelState | None, memory_gb: float | None
    ) -> None:
        """Targeted observation write for the heartbeat, leaving intent alone.

        `state=None` records "not currently observable" and clears the
        timestamp with it: a stale observation must not keep the authority of
        a fresh one. Targeted for the same reason `set_status` on nodes is —
        both admin entrances run the sweep, and a read-modify-write here would
        let them overwrite each other's whole row."""
        ...

    async def delete(self, model_id: str) -> None: ...

    async def reconcile_transient_states(self, mapping: dict[ModelState, ModelState]) -> int:
        """Rewrite each transient state to a terminal one, returning the count.

        A `downloading`, `loading` or `unloading` row is a claim by a task, and
        a task does not survive a restart. Left alone the row is a permanent
        dead end: every lifecycle operation refuses a transient state, so
        nothing but hand-edited SQL can move it. This runs at deploy to clear
        the ones a crash stranded.
        """
        ...


class NodeRepositoryPort(Protocol):
    async def get(self, node_id: str) -> Node | None: ...
    async def list_all(self) -> list[Node]: ...
    async def save(self, node: Node) -> None: ...

    async def set_status(self, node_id: str, status: NodeStatus) -> None:
        """Targeted status write for the heartbeat.

        A full-row `save` would carry the whole entity back and could revert a
        concurrent edit to the name, memory or runtimes, the same read-modify-
        write hazard the key and user repositories already avoid. The heartbeat
        runs in both admin entrances, so this also has to be idempotent, which a
        single-column update is.
        """
        ...

    async def delete(self, node_id: str) -> None: ...


class RoutingPolicyRepositoryPort(Protocol):
    async def get(self, capability: str) -> RoutingPolicy | None: ...
    async def list_all(self) -> list[RoutingPolicy]: ...
    async def save(self, policy: RoutingPolicy) -> None: ...
    async def delete(self, capability: str) -> None: ...
