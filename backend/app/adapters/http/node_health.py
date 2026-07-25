"""Node health by probing the runtimes it declares.

Each runtime adapter already answers `health()` (an HTTP reachability check
against the runtime on the host), so a node's status is an aggregate of the
runtimes it lists: online when all answer, degraded when some do, offline when
none does.

**Single-node scope, stated plainly.** The runtime adapters are built pointing at
the configured host runtime (`host.docker.internal`), not at `node.address`, so
this probes the local node correctly and would probe the *wrong* endpoint for a
second node. A second node needs per-node runtime endpoints, which do not exist
yet; that lands with multi-node routing. Until then the node whose runtimes these
adapters actually reach is the only node, so the aggregate is accurate. Any
outbound request that does use `node.address` (routing to a second node later)
goes through `adapters/http/egress_guard.py` first; see security.md section 7.2.
"""

from __future__ import annotations

import asyncio
import logging

from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.ports.model_runtime_port import ModelRuntimePort

logger = logging.getLogger(__name__)


class RuntimeNodeHealth:
    def __init__(self, runtimes: dict[RuntimeKind, ModelRuntimePort]) -> None:
        self._runtimes = runtimes

    async def probe(self, node: Node) -> NodeStatus:
        adapters = [self._runtimes[r] for r in node.runtimes if r in self._runtimes]
        if not adapters:
            # The node declares no runtime this build can reach, so its health
            # cannot be observed. Conservative rather than optimistic: reporting
            # online here would route traffic at something unverified.
            return NodeStatus.OFFLINE

        results = await asyncio.gather(
            *(self._safe_health(a) for a in adapters), return_exceptions=False
        )
        healthy = sum(1 for ok in results if ok)
        if healthy == len(results):
            return NodeStatus.ONLINE
        if healthy == 0:
            return NodeStatus.OFFLINE
        return NodeStatus.DEGRADED

    async def _safe_health(self, adapter: ModelRuntimePort) -> bool:
        """A runtime adapter's `health()` returns False on an unreachable host,
        but an unexpected error must not abort the whole probe: one broken
        runtime reads as that runtime being down, not as the node's status being
        unknowable."""
        try:
            return await adapter.health()
        except Exception:  # noqa: BLE001
            logger.warning("a runtime health check raised during a node probe", exc_info=True)
            return False
