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
cannot be reached leaves the observation null, which readers treat as "trust
intent", the pre-observation behaviour.

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
from app.adapters.persistence.repositories import PostgresModelRepository, PostgresNodeRepository
from app.domain.entities.model import Model, ModelState, RuntimeKind, RuntimeResidency
from app.domain.entities.node import Node, NodeStatus
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.node_health_port import NodeHealthPort
from app.infrastructure.config import get_settings
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)

NodesSource = Callable[[], Awaitable[list[Node]]]
StatusWriter = Callable[[str, NodeStatus], Awaitable[None]]
ModelsSource = Callable[[], Awaitable[list[Model]]]
ObservationWriter = Callable[[str, ModelState | None, float | None], Awaitable[None]]


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
) -> int:
    """Ask each runtime what it holds and reconcile every registered model.

    Returns the count of models whose observation moved. Same single-node scope
    as `RuntimeNodeHealth`, and `local_node_id` is what makes it explicit: the
    adapters point at the configured host runtime, so only that node's models
    can be observed and every other node's are left unobserved rather than
    guessed at.

    A runtime that raises or answers None contributes no observation, and the
    models it serves are written back to "not observed" rather than left
    holding a stale one: a claim that cannot be re-checked must not keep the
    authority of one that just was.
    """
    residencies: dict[RuntimeKind, RuntimeResidency | None] = {}
    for kind, adapter in runtimes.items():
        try:
            residencies[kind] = await adapter.residency()
        except Exception:  # noqa: BLE001 - one broken runtime must not stop the sweep
            logger.warning("a runtime residency probe raised", exc_info=True)
            residencies[kind] = None

    changed = 0
    for model in await models():
        residency = residencies.get(model.runtime)
        observed: ModelState | None
        observed_gb: float | None = None
        if model.node_id != local_node_id:
            # The adapters are built pointing at the configured host runtime, not
            # at `node.address`, so a second node's residency is not something
            # this sweep can see. Left unobserved rather than reported absent:
            # `not_downloaded` here would be a *confident wrong answer*, and
            # because routing now ranks observation over intent it would refuse
            # every model on that node and make the memory budget count node B's
            # rows against node A's runtime. `RuntimeNodeHealth` carries the same
            # single-node limitation, where the cost is only a wrong node status.
            # Per-node runtime endpoints land with multi-node routing.
            observed = None
        elif residency is None:
            observed = None
        elif model.ref in residency.resident:
            observed = ModelState.LOADED
            observed_gb = residency.resident[model.ref]
        elif model.ref in residency.on_disk:
            observed = ModelState.DOWNLOADED
        else:
            observed = ModelState.NOT_DOWNLOADED

        unchanged = model.observed_state is observed and model.observed_memory_gb == observed_gb

        # An unchanged observation is still rewritten, so that `observed_at`
        # means *last observed* rather than *last changed*. Writing only on
        # change left these rows stamped 2026-07-30 for five days while the
        # sweep ran every thirty seconds, which made a model steadily observed
        # for five days and a heartbeat dead for five days the same row — the
        # ambiguity `check-platform-health.sh` argues against in its own
        # header. The churn this was avoiding also halved on 2026-08-04, when
        # the sweep stopped running in both admin entrances at once.
        #
        # Except when there is nothing to stamp: `set_observed` nulls
        # `observed_at` along with the state, so rewriting an already-null row
        # buys no freshness and is pure churn. A model on another node, or one
        # whose runtime has no adapter, stays untouched.
        if unchanged and observed is None:
            continue
        await write_observation(model.id, observed, observed_gb)
        if unchanged:
            continue
        # Counted and logged only on a change: the return value feeds the
        # "what did this sweep do" line, and logging an unchanged observation
        # thirty times a minute would bury the transitions that matter.
        changed += 1
        logger.info(
            "model %s observed %s (intent %s)",
            model.alias,
            observed.value if observed else "nothing",
            model.state.value,
        )
    return changed


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
        model_id: str, state: ModelState | None, memory_gb: float | None
    ) -> None:
        async with session_scope() as session:
            await PostgresModelRepository(session).set_observed(model_id, state, memory_gb)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sweep(health, load_nodes, write_status)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("node heartbeat sweep failed")
        try:
            await observe_models(
                app.state.runtimes,
                load_models,
                write_observation,
                get_settings().node_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("model observation sweep failed")
