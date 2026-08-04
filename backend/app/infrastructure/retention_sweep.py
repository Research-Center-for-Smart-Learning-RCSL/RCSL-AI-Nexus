"""The scheduled half of retention.

The policy is a number in a table; something has to act on it, or it is a
statement of intent that deletes nothing. This is that something: a loop in the
admin application that applies every stored window on an interval.

**It runs in the admin application, and both facts about how matter**, for the
same reasons as the node heartbeat next door. The gateway cannot host it —
section 6's least-privilege split gives that account `INSERT` on
`usage_records` and nothing else, so it could not delete a row if it tried. And
both admin entrances run it, because they are one image with no natural single
owner; a `DELETE ... WHERE at < cutoff` run twice deletes nothing the second
time, which is what makes that safe rather than merely tolerable.

It sleeps before its first sweep, so a process that starts and stops the
lifespan quickly — every test that builds the admin app — cancels the task
during that first sleep and never touches the database. That is not a
convenience: without it, a test suite would silently purge whatever fixture
data it had just written.

The interval is a day by default rather than an hour. Retention is measured in
months, so a sweep that runs twelve times more often deletes the same rows
twelve times later at best, and the cost of being a day late is a day of rows
that were already past their window while nobody was looking at them.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from app.adapters.persistence.repositories import (
    PostgresRecordPurge,
    PostgresRetentionPolicyRepository,
)
from app.adapters.persistence.sqlalchemy_models import AuditLogRow, UsageRecordRow
from app.application.use_cases.manage_retention import ManageRetention
from app.domain.entities.retention import RetentionDataset
from app.infrastructure.db import session_scope
from app.shared.clock import SystemClock

logger = logging.getLogger(__name__)


async def run_retention_sweep(app: FastAPI, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sweep_once(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed sweep must not end the loop. The next one deletes the
            # same rows plus a day's worth, so recovery is automatic and the
            # only lasting cost of an exception here is the log line.
            logger.exception("retention_sweep_failed")


async def sweep_once(app: FastAPI) -> None:
    async with session_scope() as session:
        use_case = ManageRetention(
            policies=PostgresRetentionPolicyRepository(session),
            purges={
                RetentionDataset.AUDIT_LOG: PostgresRecordPurge(session, AuditLogRow),
                RetentionDataset.USAGE_RECORDS: PostgresRecordPurge(session, UsageRecordRow),
            },
            authz=app.state.authz,
            audit=app.state.audit,
            clock=SystemClock(),
        )
        outcomes = await use_case.purge_due()

    # One line per sweep, and only when it removed something. A daily line
    # saying "deleted 0" for a year is a line nobody reads by the time it says
    # something else.
    removed = {o.dataset.value: o.deleted for o in outcomes if o.deleted}
    if removed:
        logger.info("retention_swept", extra={"removed": removed})
