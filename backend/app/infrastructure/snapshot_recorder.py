"""Periodic platform snapshot recorder.

Writes one row to `platform_snapshots` every interval, so the dashboard can
show sparklines for entity counts that have no natural time-series source.
Follows the heartbeat pattern: sleep-first, CancelledError re-raised, broad
except catches everything else. Only the tailnet entrance runs it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models.observability_retention import (
    PlatformSnapshotRow,
)
from app.domain.entities.model import ModelState
from app.domain.entities.node import NodeStatus
from app.infrastructure.db import session_scope

logger = logging.getLogger(__name__)


async def run_snapshot_recorder(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _record_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("platform snapshot recording failed")


async def _record_snapshot() -> None:
    now = datetime.now(UTC)

    async with session_scope() as session:
        models = await PostgresModelRepository(session).list_all()
        nodes = await PostgresNodeRepository(session).list_all()
        keys = await PostgresApiKeyRepository(session, tenant_id=None).list_all()
        users = await PostgresUserRepository(session, tenant_id=None).list_all()

        row = PlatformSnapshotRow(
            at=now,
            models_loaded=sum(1 for m in models if m.state is ModelState.LOADED),
            models_total=len(models),
            nodes_online=sum(1 for n in nodes if n.status is NodeStatus.ONLINE),
            nodes_total=len(nodes),
            api_keys_active=sum(1 for k in keys if k.is_active(now)),
            users_total=len(users),
        )
        session.add(row)
        await session.commit()

    logger.debug("platform snapshot recorded at %s", now.isoformat())


@dataclass(frozen=True, slots=True)
class SnapshotPoint:
    t: str
    models_loaded: int
    models_total: int
    nodes_online: int
    nodes_total: int
    api_keys_active: int
    users_total: int


async def recent_snapshots(hours: int = 48) -> list[SnapshotPoint]:
    """Return snapshots from the last `hours` hours, oldest first."""
    from datetime import timedelta

    cutoff = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours)

    async with session_scope() as session:
        result = await session.execute(
            select(PlatformSnapshotRow)
            .where(PlatformSnapshotRow.at >= cutoff)
            .order_by(PlatformSnapshotRow.at.asc())
        )
        rows = result.scalars().all()

    return [
        SnapshotPoint(
            t=r.at.isoformat(),
            models_loaded=r.models_loaded,
            models_total=r.models_total,
            nodes_online=r.nodes_online,
            nodes_total=r.nodes_total,
            api_keys_active=r.api_keys_active,
            users_total=r.users_total,
        )
        for r in rows
    ]
