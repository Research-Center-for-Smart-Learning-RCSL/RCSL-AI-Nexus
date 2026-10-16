"""One-shot provisioning, run beside the migration.

Phase 1 needs one row that no endpoint creates: the compute node models
attach to. A node write endpoint has to ship with the SSRF guard, because a
node record is an address the platform will then make outbound requests to
(docs/architecture/security.md section 7.2), so the single node is named in
configuration instead.

**It runs here rather than in the admin lifespan, and both reasons matter.**

Starting the two admin entrances at once raced: `merge()` is a SELECT then an
INSERT, not an upsert, so on an empty table both services could select nothing
and the loser hit a unique violation during its own startup. The `migrate`
service already exists precisely because "three containers start from the same
image and would race each other", and every application gates on it.

And an application that writes to the database at startup cannot be
constructed without one, which broke the promise in the README that the unit
suite never reaches a real database: eight tests that only exercise HTTP
wiring began failing the moment Postgres was absent.

Run as `python -m app.infrastructure.provision`, after `alembic upgrade head`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping

from app.adapters.persistence.repositories import (
    PostgresKnowledgeRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
)
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import dispose_engine, init_engine, session_scope

logger = logging.getLogger(__name__)

# Where a crash mid-operation leaves a model, and where the next deploy should
# move it. A load or unload interrupted in flight may have left the weights in
# either state, so the conservative reading is that they are resident and a
# `LOADING` becomes `ERROR` for an operator to retry, while an `UNLOADING`
# becomes `LOADED` because the memory it holds must keep being counted. A
# `DOWNLOADING` had nothing on disk to protect and becomes `ERROR`.
TRANSIENT_RECONCILIATION = {
    ModelState.DOWNLOADING: ModelState.ERROR,
    ModelState.LOADING: ModelState.ERROR,
    ModelState.UNLOADING: ModelState.LOADED,
}


def build_local_node(settings: Settings) -> Node:
    if settings.node_agent_enabled and not settings.node_agent_url:
        # Refused rather than written as NULL (review on #32): with the agent
        # on, a node without an address is refused, so the deploy would come
        # up "healthy" and every chat request would find no runtime.
        raise ValueError(
            "NODE_AGENT_ENABLED is set but NODE_AGENT_URL is empty; deploy with "
            "docker-compose.node-agent.yml, which sets it, or turn the agent off"
        )
    return Node(
        id=settings.node_id,
        name=settings.node_name,
        # The tailnet address, not the Ollama URL: this is how another node
        # would reach it. `total_memory_gb` is the only field Phase 1 reads,
        # and the memory budget refuses a load against it, so a stale value is
        # the difference between a refusal and driving the host into swap.
        address=settings.tailnet_ip,
        # A starting assumption only: the heartbeat re-probes this within one
        # interval and overwrites it with what it observes.
        status=NodeStatus.ONLINE,
        total_memory_gb=settings.node_total_memory_gb,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
        # From configuration like everything else here, because this row is
        # rewritten on every deploy: an address set by hand would be cleared.
        agent_url=settings.node_agent_url or None,
    )


def agent_node_mismatch(settings: Settings, environ: Mapping[str, str]) -> str | None:
    """The agent's node id when it is not the row provisioned here.

    The address goes to `NODE_ID`'s row while the agent claims
    `NODE_AGENT_NODE_ID`'s, so requests routed there reach an agent that
    answers for another node. Warned rather than refused: the agent's own setting is only
    visible here when `.env` carries it, so its absence proves nothing.
    """
    agent_node = environ.get("NODE_AGENT_NODE_ID")
    if settings.node_agent_enabled and agent_node and agent_node != settings.node_id:
        return agent_node
    return None


async def provision() -> None:
    settings = get_settings()
    node = build_local_node(settings)
    if (agent_node := agent_node_mismatch(settings, os.environ)) is not None:
        logger.warning(
            "NODE_AGENT_NODE_ID=%s differs from NODE_ID=%s; the agent address "
            "goes to the NODE_ID row",
            agent_node,
            settings.node_id,
        )
    init_engine(settings)
    try:
        async with session_scope() as session:
            # Rewritten on every run, so changing NODE_TOTAL_MEMORY_GB after
            # moving to different hardware takes effect without anyone editing
            # a row by hand.
            await PostgresNodeRepository(session).save(node)
        logger.info("local_node_ready id=%s memory_gb=%s", node.id, node.total_memory_gb)

        async with session_scope() as session:
            moved = await PostgresModelRepository(session).reconcile_transient_states(
                TRANSIENT_RECONCILIATION
            )
        if moved:
            logger.warning("reconciled %s model(s) stranded in a transient state by a crash", moved)

        async with session_scope() as session:
            # Unscoped on purpose: this runs at deploy on behalf of no caller,
            # and a crash strands documents in every tenant, not just one.
            stranded = await PostgresKnowledgeRepository.unscoped(
                session
            ).reconcile_transient_documents("Interrupted by a restart. Upload again to retry.")
        if stranded:
            logger.warning("reconciled %s document(s) stranded mid-ingestion", stranded)
    finally:
        await dispose_engine()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(provision())
    return 0


if __name__ == "__main__":
    sys.exit(main())
