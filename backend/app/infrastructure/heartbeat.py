"""Node status heartbeat.

Periodically probes every node and writes the status it observes, so a routing
requirement of `node_status: [online]` stops selecting a node whose runtime has
gone away instead of always holding. Before this, status was written once at
provision and never revisited.

**It runs in the admin application, and both facts about how matter.** The
gateway cannot host it: section 6's least-privilege split lets the gateway write
only `usage_records`, never `nodes`. And the two admin entrances both run it,
because they are the same image with no natural single owner, which is why the
write is the idempotent targeted `set_status` and why a status is written only
when it actually changed rather than every sweep.

The loop sleeps before its first sweep so that a process which starts and stops
the lifespan quickly (every test that builds the admin app) cancels the task
during that first sleep and never touches the database or a runtime.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI

from app.adapters.http.node_health import RuntimeNodeHealth
from app.adapters.persistence.repositories import PostgresNodeRepository
from app.domain.entities.node import Node, NodeStatus
from app.domain.ports.node_health_port import NodeHealthPort
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)

NodesSource = Callable[[], Awaitable[list[Node]]]
StatusWriter = Callable[[str, NodeStatus], Awaitable[None]]


async def sweep(health: NodeHealthPort, nodes: NodesSource, write_status: StatusWriter) -> int:
    """Probe every node once, writing status only where it changed.

    Returns the count of nodes whose status moved. The probe (network I/O) and
    the write are separated by the caller's `nodes` and `write_status`, each of
    which opens its own short transaction, so a slow or hung runtime never pins a
    database connection for the length of a probe.
    """
    changed = 0
    for node in await nodes():
        observed = await health.probe(node)
        if observed is node.status:
            continue
        changed += 1
        await write_status(node.id, observed)
        logger.info("node %s status %s -> %s", node.id, node.status.value, observed.value)
    return changed


async def run_heartbeat(app: FastAPI, interval_seconds: int) -> None:
    health = RuntimeNodeHealth(app.state.runtimes)

    async def load_nodes() -> list[Node]:
        async with session_scope() as session:
            return await PostgresNodeRepository(session).list_all()

    async def write_status(node_id: str, status: NodeStatus) -> None:
        async with session_scope() as session:
            await PostgresNodeRepository(session).set_status(node_id, status)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sweep(health, load_nodes, write_status)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("node heartbeat sweep failed")
