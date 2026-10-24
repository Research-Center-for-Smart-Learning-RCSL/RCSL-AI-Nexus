"""Wiring for the residency reconciler loop (#49).

It runs in the tailnet admin, the heartbeat's single owner, and only when
`RESIDENCY_RECONCILER_ENABLED` is set, node agents are enabled, and the
heartbeat is running. Each read is its own short transaction; no transaction
is held across a runtime call except the load's own, as on the operator path.

Two admin processes, or a restarted one overlapping its predecessor, are kept
apart per node by a session advisory lock on a dedicated connection that is
idle, not in a transaction, while the pass runs. An operator's Load takes the
same lock, so the two never pass the memory budget together. The pass is
skipped, never queued, when another holder has the node.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import FastAPI
from sqlalchemy import text

from app.adapters.persistence.node_serialisation import PostgresNodeSerialisation
from app.adapters.persistence.repositories import (
    PostgresMaintenanceRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
)
from app.application.use_cases.reconcile_residency import (
    PassResult,
    ReconcileResidency,
    Suspension,
)
from app.domain.entities.model import Model
from app.domain.entities.node import Node
from app.infrastructure.config import Settings
from app.infrastructure.db import get_engine, session_scope
from app.infrastructure.di.inference_runtime import manage_models_for
from app.infrastructure.heartbeat import database_time, observe_node

logger = logging.getLogger(__name__)

RAISED_OUTCOME = "error"
"""The outcome label for a pass that raised before any node was judged, such
as the node list being unreadable. Per-node failures are `failed`."""


class PostgresReconcilerState:
    async def nodes(self) -> list[Node]:
        async with session_scope() as session:
            return await PostgresNodeRepository(session).list_all()

    async def models_on(self, node_id: str) -> list[Model]:
        async with session_scope() as session:
            return [
                m for m in await PostgresModelRepository(session).list_all() if m.node_id == node_id
            ]

    async def node_blocked(self, node_id: str) -> bool:
        async with session_scope() as session:
            blocked = await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM node_operations "
                    "WHERE node_id = :node AND state = 'outcome_unknown')"
                ),
                {"node": node_id},
            )
            return bool(blocked.scalar_one())

    async def now(self) -> datetime:
        return await database_time()


class HeartbeatObserver:
    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def observe(self, node: Node) -> None:
        await observe_node(self._app.state.runtimes, node)


class ManageModelsRestorer:
    """One transaction per call, as one operator request would have."""

    def __init__(self, app: FastAPI, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def restore(self, model_id: str) -> Model:
        async with session_scope() as session:
            return await manage_models_for(self._app, session, self._settings).restore(model_id)

    async def release(self, model_id: str) -> Model:
        async with session_scope() as session:
            return await manage_models_for(self._app, session, self._settings).release(model_id)


async def maintenance_hold() -> bool:
    """Suspended while the platform is closed for maintenance (#61).

    Read before each node's pass and again before each load, from the same row
    every entrance reads, so a hold landing mid-pass stops the next load. The
    desired set is left alone: maintenance suspends the reconciler, it does not
    rewrite what operators asked to keep resident.
    """
    async with session_scope() as session:
        state = await PostgresMaintenanceRepository(session).read()
    return state.admission_closed


def reconciler_should_run(app: FastAPI, settings: Settings) -> bool:
    if not settings.residency_reconciler_enabled:
        return False
    if not getattr(app.state.runtimes, "agents_enabled", False):
        logger.warning(
            "RESIDENCY_RECONCILER_ENABLED is set but node agents are not; it stays idle, "
            "because only the agent can refuse a load while the node is blocked"
        )
        return False
    if settings.node_heartbeat_interval_seconds <= 0:
        logger.warning(
            "RESIDENCY_RECONCILER_ENABLED is set but the heartbeat is off; with no "
            "observations it would never act, so it is not started"
        )
        return False
    return True


async def run_residency_reconciler(
    app: FastAPI, settings: Settings, *, suspended: Suspension = maintenance_hold
) -> None:
    reconciler = ReconcileResidency(
        PostgresReconcilerState(),
        HeartbeatObserver(app),
        ManageModelsRestorer(app, settings),
        PostgresNodeSerialisation(get_engine),
        enabled=settings.residency_reconciler_enabled,
        suspended=suspended,
    )
    passes = app.state.metrics.residency_reconcile
    # Every outcome exported at zero from the start, so `increase()` sees the
    # first give-up rather than a series that appears already at one.
    for result in (*PassResult, RAISED_OUTCOME):
        passes.labels(result)
    while True:
        # Sleep first, as the heartbeat does, so a lifespan that opens and
        # closes quickly never reaches the database or a runtime.
        await asyncio.sleep(settings.residency_reconciler_interval_seconds)
        try:
            outcomes = await reconciler.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed pass must not kill the loop
            logger.exception("residency reconciliation pass failed")
            passes.labels(RAISED_OUTCOME).inc()
            continue
        for outcome in outcomes:
            passes.labels(outcome.result.value).inc()
