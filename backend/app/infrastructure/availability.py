"""Quiet-host availability, derived from committed control-plane evidence.

The tailnet admin owns the periodic reader, independently of the runtime
heartbeat: a hung probe must not stop the last observation from aging out.
No agent endpoint or runtime is contacted here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.repositories import (
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
)
from app.application.use_cases.capability_availability import (
    CapabilityAvailability,
    assess_availability,
)
from app.domain.entities.model import RuntimeKind
from app.domain.ports.model_runtime_port import ModelRuntimePort, runtime_for
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)
AVAILABILITY_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class AvailabilitySnapshot:
    at: datetime
    capabilities: list[CapabilityAvailability]
    unresolved: dict[str, int]
    silent_outage: bool


async def read_availability(
    session: AsyncSession, runtimes: dict[RuntimeKind, ModelRuntimePort]
) -> AvailabilitySnapshot:
    # One short repeatable-read transaction is used by the periodic caller.
    # The request reader likewise performs no network I/O or runtime actions.
    now = (await session.execute(text("SELECT now()"))).scalar_one()
    models = await PostgresModelRepository(session).list_all()
    nodes = await PostgresNodeRepository(session).list_all()
    policies = await PostgresRoutingPolicyRepository(session).list_all()
    counts = await session.execute(
        text(
            "SELECT node_id, count(*) FROM node_operations "
            "WHERE state = 'outcome_unknown' GROUP BY node_id"
        )
    )
    unresolved = {n.id: 0 for n in nodes}
    unresolved.update({row[0]: row[1] for row in counts})
    silent = (
        await session.execute(
            text(
                "SELECT NOT EXISTS (SELECT 1 FROM usage_records "
                "WHERE completed AND at >= now() - interval '24 hours') "
                "AND EXISTS (SELECT 1 FROM refusals "
                "WHERE surface = 'gateway' AND at >= now() - interval '24 hours')"
            )
        )
    ).scalar_one()
    by_node = {n.id: n for n in nodes}
    unavailable = frozenset(
        m.id for m in models if runtime_for(runtimes, by_node.get(m.node_id), m.runtime) is None
    )
    return AvailabilitySnapshot(
        now,
        assess_availability(policies, models, nodes, unresolved, unavailable, now),
        unresolved,
        bool(silent),
    )


async def run_availability(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(AVAILABILITY_INTERVAL_SECONDS)
        try:
            async with asyncio.timeout(20):
                async with session_scope() as session:
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                    snapshot = await read_availability(session, app.state.runtimes)
            instruments = app.state.metrics
            instruments.capability_available.clear()
            for item in snapshot.capabilities:
                if item.enabled:
                    instruments.capability_available.labels(item.capability).set(
                        int(item.available)
                    )
            instruments.node_operation_unresolved.clear()
            for node, count in snapshot.unresolved.items():
                instruments.node_operation_unresolved.labels(node).set(count)
            instruments.silent_outage.set(int(snapshot.silent_outage))
            instruments.availability_observed_at.set(snapshot.at.timestamp())
        except Exception:
            # Keep the last timestamp on failure. The stale-observer alert is
            # what distinguishes a quiet healthy platform from a dead reader.
            logger.exception("availability observation failed")
