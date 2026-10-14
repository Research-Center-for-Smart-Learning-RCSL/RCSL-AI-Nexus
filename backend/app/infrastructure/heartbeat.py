"""Node status and model residency heartbeat.

Periodically probes every node and writes the status it observes, so a routing
requirement of `node_status: [online]` stops selecting a node whose runtime has
gone away instead of always holding. Before this, status was written once at
provision and never revisited.

The same loop reconciles model residency: each runtime that can answer is
asked what it actually holds, and the answer lands in the registry's
`observed_*` columns next to the intent it may contradict. `state` said
`loaded` for hours on 2026-07-27 while Ollama held nothing — a restart, an
out-of-band `ollama rm`, or an eviction all leave that assertion standing, and
this is the read-back that catches it. A runtime that cannot answer (MLX) or
cannot be reached leaves the observation null. Routing may trust intent only
for unobservable runtimes; Ollama requires fresh positive residency evidence.

**It runs in the tailnet admin application.** The
gateway cannot host it: section 6's least-privilege split lets the gateway write
only `usage_records`, never `nodes`. The public entrance does not run this
loop. Status is written through the targeted `set_status` only when changed.

The loop sleeps before its first sweep so that a process which starts and stops
the lifespan quickly (every test that builds the admin app) cancels the task
during that first sleep and never touches the database or a runtime.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import cast

from fastapi import FastAPI
from sqlalchemy import text

from app.adapters.http.node_health import RuntimeNodeHealth
from app.adapters.persistence.repositories import PostgresModelRepository, PostgresNodeRepository
from app.domain.entities.model import Model, ModelState, RuntimeKind, RuntimeResidency
from app.domain.entities.node import Node, NodeStatus
from app.domain.ports.model_runtime_port import ModelRuntimePort, runtime_for
from app.domain.ports.node_health_port import NodeHealthPort
from app.infrastructure.config import get_settings
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)

NodesSource = Callable[[], Awaitable[list[Node]]]
StatusWriter = Callable[[str, NodeStatus], Awaitable[None]]
ModelsSource = Callable[[], Awaitable[list[Model]]]
ObservationWriter = Callable[
    [str, ModelState | None, float | None, datetime | None], Awaitable[None]
]
ObservationTime = Callable[[], Awaitable[datetime]]


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


async def observe_models(
    runtimes: dict[RuntimeKind, ModelRuntimePort],
    models: ModelsSource,
    write_observation: ObservationWriter,
    local_node_id: str,
    *,
    observation_time: ObservationTime,
    local_node: Node | None = None,
    nodes_by_id: dict[str, Node] | None = None,
) -> int:
    """Ask each runtime what it holds and reconcile every registered model.

    Returns the count of models whose observation moved. With agents enabled,
    each node is observed through its own adapter. Direct adapters still point
    at one configured host: only local_node_id may use those, so the local
    host's answer can never be attributed to a different node.

    A runtime that raises or answers None contributes no observation, and the
    models it serves are written back to "not observed" rather than left
    holding a stale one: a claim that cannot be re-checked must not keep the
    authority of one that just was.
    """
    registered = await models()
    nodes_by_id = dict(nodes_by_id or {})
    if local_node is not None:
        nodes_by_id.setdefault(local_node.id, local_node)
    agents_enabled = bool(getattr(runtimes, "agents_enabled", False))
    groups: dict[tuple[str, RuntimeKind], list[Model]] = {}
    for model in registered:
        groups.setdefault((model.node_id, model.runtime), []).append(model)

    changed = 0
    for (node_id, kind), group in groups.items():
        # A direct adapter has no endpoint for a different node. Only an
        # agent-backed directory may resolve that node's own residency.
        adapter = None
        if node_id == local_node_id or agents_enabled:
            adapter = runtime_for(runtimes, nodes_by_id.get(node_id), kind)
        residency: RuntimeResidency | None = None
        observed_at = None
        if adapter is not None:
            # Database time before the probe conservatively includes probe
            # and write latency. One frozen time for the whole answer prevents
            # a delayed first write from freshening its siblings' old evidence.
            # The provider closes its transaction before runtime network I/O.
            observed_at = await observation_time()
            try:
                residency = await adapter.residency()
            except Exception:  # noqa: BLE001 - one broken runtime must not stop the sweep
                logger.warning("a runtime residency probe raised", exc_info=True)

        # Write this answer before awaiting another node. Otherwise a slow
        # later probe could delay an old positive observation for minutes and
        # then stamp it as newly observed, defeating the routing age limit.
        for model in group:
            observed: ModelState | None
            observed_gb: float | None = None
            if residency is None:
                observed = None
            elif model.ref in residency.resident:
                observed = ModelState.LOADED
                observed_gb = residency.resident[model.ref]
            elif model.ref in residency.on_disk:
                observed = ModelState.DOWNLOADED
            else:
                observed = ModelState.NOT_DOWNLOADED

            unchanged = model.observed_state is observed and model.observed_memory_gb == observed_gb
            # A repeated positive observation refreshes observed_at, while an
            # already-null observation has no timestamp to refresh. Only an
            # actual transition is counted and logged.
            if unchanged and observed is None:
                continue
            await write_observation(
                model.id, observed, observed_gb, observed_at if observed else None
            )
            if unchanged:
                continue
            changed += 1
            logger.info(
                "model %s observed %s (intent %s)",
                model.alias,
                observed.value if observed else "nothing",
                model.state.value,
            )
    return changed


async def observe_runtime_version(
    runtimes: dict[RuntimeKind, ModelRuntimePort],
    nodes: NodesSource,
    write_version: Callable[[str, str | None], Awaitable[None]],
) -> None:
    """Stamp each node's Ollama version, through its own runtime (its agent
    when agents are enabled), for the validated-profile key (PR2b on #24).

    A runtime that cannot say clears the stamp: a version that can no longer
    be re-read must not keep keying a profile.
    """
    for node in await nodes():
        if RuntimeKind.OLLAMA not in node.runtimes:
            continue
        runtime = runtime_for(runtimes, node, RuntimeKind.OLLAMA)
        read = getattr(runtime, "runtime_version", None)
        version = await read() if callable(read) else None
        # Every sweep while it answers, so the stamp stays fresh; once when it
        # stops, to clear it.
        if version is not None or node.runtime_version is not None:
            await write_version(node.id, version)


async def run_heartbeat(app: FastAPI, interval_seconds: int) -> None:
    health = RuntimeNodeHealth(app.state.runtimes)

    async def load_nodes() -> list[Node]:
        async with session_scope() as session:
            return await PostgresNodeRepository(session).list_all()

    async def write_status(node_id: str, status: NodeStatus) -> None:
        async with session_scope() as session:
            await PostgresNodeRepository(session).set_status(node_id, status)

    async def load_models() -> list[Model]:
        async with session_scope() as session:
            return await PostgresModelRepository(session).list_all()

    async def write_observation(
        model_id: str,
        state: ModelState | None,
        memory_gb: float | None,
        observed_at: datetime | None,
    ) -> None:
        async with session_scope() as session:
            await PostgresModelRepository(session).set_observed(
                model_id, state, memory_gb, observed_at=observed_at
            )

    async def observation_time() -> datetime:
        async with session_scope() as session:
            return cast(
                datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            )

    async def write_version(node_id: str, version: str | None) -> None:
        async with session_scope() as session:
            await PostgresNodeRepository(session).set_runtime_version(node_id, version)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sweep(health, load_nodes, write_status)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("node heartbeat sweep failed")
        try:
            await observe_runtime_version(app.state.runtimes, load_nodes, write_version)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("runtime version sweep failed")
        try:
            local_id = get_settings().node_id
            nodes_by_id = {n.id: n for n in await load_nodes()}
            await observe_models(
                app.state.runtimes,
                load_models,
                write_observation,
                local_id,
                observation_time=observation_time,
                nodes_by_id=nodes_by_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("model observation sweep failed")
