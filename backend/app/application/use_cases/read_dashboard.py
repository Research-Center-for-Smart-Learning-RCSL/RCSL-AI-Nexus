"""The overview figures.

Counted from the tables rather than from a metrics system. `MetricsPort` and
Prometheus arrive in Phase 2 and bring the things a database cannot answer:
memory in use right now, tokens per second, node temperature. What is here is
the part the database already knows, and there is no reason for it to wait.

The counts are `len()` over full listings on purpose. Every table involved
holds tens of rows on this deployment, and five dedicated `COUNT` methods on
five repository ports would be more code defending against a scale that is
not coming. The usage aggregate is the exception: `usage_records` grows per
request, so it is a real aggregate over an index.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.model import ModelState
from app.domain.entities.node import NodeStatus
from app.domain.ports.repositories import (
    ApiKeyRepositoryPort,
    ModelRepositoryPort,
    NodeRepositoryPort,
    UsageRepositoryPort,
    UserRepositoryPort,
)
from app.domain.ports.security_ports import AuthorizationPort
from app.shared.clock import Clock

WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    models_total: int
    models_loaded: int
    nodes_online: int
    nodes_total: int
    api_keys_active: int
    users_total: int
    requests_last_24h: int
    tokens_last_24h: int


class ReadDashboard:
    def __init__(
        self,
        models: ModelRepositoryPort,
        nodes: NodeRepositoryPort,
        keys: ApiKeyRepositoryPort,
        users: UserRepositoryPort,
        usage: UsageRepositoryPort,
        authz: AuthorizationPort,
        clock: Clock,
    ) -> None:
        self._models = models
        self._nodes = nodes
        self._keys = keys
        self._users = users
        self._usage = usage
        self._authz = authz
        self._clock = clock

    async def execute(self, actor: Actor) -> DashboardSummary:
        # Usage totals are the whole platform's, not the caller's, so this
        # needs the wider scope rather than `usage:read_own`.
        self._authz.require(actor, Scope.USAGE_READ_ALL)

        now = self._clock.now()
        models = await self._models.list_all()
        nodes = await self._nodes.list_all()
        keys = await self._keys.list_all()
        users = await self._users.list_all()
        requests, tokens = await self._usage.totals_since(now - WINDOW)

        return DashboardSummary(
            models_total=len(models),
            models_loaded=sum(1 for m in models if m.state is ModelState.LOADED),
            nodes_online=sum(1 for n in nodes if n.status is NodeStatus.ONLINE),
            nodes_total=len(nodes),
            # Active means usable right now: neither revoked nor expired. A
            # count of rows would include keys that stopped working months ago.
            api_keys_active=sum(1 for k in keys if k.is_active(now)),
            users_total=len(users),
            requests_last_24h=requests,
            tokens_last_24h=tokens,
        )
