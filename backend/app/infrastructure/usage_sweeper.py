"""Settles agent-backed usage nobody settled (design R6 and revision 6 on #24).

The gateway settles an attempt's usage when its stream ends. This covers what
that cannot: a client that left while the agent drained to `done`, a gateway
that died between the agent's terminal commit and its own write, and a
delivery flag committed after the row was inserted. It writes exactly the row
the gateway would have, through the same `PostgresUsageSettlement`, so the two
racing each other still leaves one row.

Runs on the tailnet admin entrance only, like the heartbeat, and only while
node agents are enabled.
"""

from __future__ import annotations

import asyncio
import logging

from app.adapters.metrics.prometheus import Metrics
from app.adapters.persistence.repositories import PostgresUsageSettlement
from app.infrastructure.db import get_session_factory

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 30


async def run_usage_sweeper(
    metrics: Metrics | None = None, interval_seconds: int = SWEEP_INTERVAL_SECONDS
) -> None:
    # What the sweeper settles is counted on this entrance's `/metrics`, so the
    # gateway's and this one's together count every attempt once.
    settlement = PostgresUsageSettlement(
        get_session_factory(), observe=metrics.observe_inference if metrics else None
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            settled = await settlement.sweep()
            if settled:
                logger.info("usage sweeper settled %s attempts", settled)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the next sweep finds the same attempts
            logger.exception("usage sweep failed")
