"""Making the configured node exist.

Phase 1 runs on one machine, and the model registry needs a node to attach
models to. That node is not registered through the API, for a reason recorded
in `docs/architecture/security.md` section 7.2: registering a node means
storing an address the platform will then make outbound requests to, so a
write endpoint has to ship alongside the SSRF guard rather than before it.
Configuration is the safe way to name the one node that already exists.

Idempotent, and written on every admin start so that changing
`NODE_TOTAL_MEMORY_GB` after moving to different hardware takes effect without
anyone editing a row by hand. The memory budget reads that number, so a stale
value is the difference between refusing a load and driving the host into
swap.
"""

from __future__ import annotations

import logging

from app.adapters.persistence.repositories import PostgresNodeRepository
from app.domain.entities.model import RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.infrastructure.config import Settings
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)


async def ensure_local_node(settings: Settings) -> None:
    node = Node(
        id=settings.node_id,
        name=settings.node_name,
        # The tailnet address, not the Ollama URL: this is how another node
        # would reach it, and `total_memory_gb` is the only field Phase 1
        # actually reads.
        address=settings.tailnet_ip,
        # Phase 1 has no heartbeat, so a configured node is online by
        # definition. `NodeHealthPort` arrives in Phase 2 and this becomes a
        # observed value rather than an assumption.
        status=NodeStatus.ONLINE,
        total_memory_gb=settings.node_total_memory_gb,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )

    async with session_scope() as session:
        await PostgresNodeRepository(session).save(node)

    logger.info(
        "local_node_ready id=%s memory_gb=%s",
        node.id,
        node.total_memory_gb,
    )
