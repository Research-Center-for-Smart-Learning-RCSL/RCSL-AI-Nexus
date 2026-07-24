"""Audit log writer.

**Every record is written in its own transaction, not the caller's.** That is
the whole design of this adapter and it is a deliberate trade.

`session_scope` rolls back on any exception, so an audit row written through
the request's session vanishes exactly when the request failed. Failures are
the entries an audit log exists for: a rejected login, a refused invitation, a
denied authorization. An audit trail that records only successes is worse than
none, because it looks complete.

The cost of the independent transaction is the mirror case: an action that is
audited and then rolls back for an unrelated reason leaves a row describing
something that did not happen. `outcome` is what makes that readable, so
callers record `success` only once the work has landed, and record the
attempt separately when the attempt itself is the interesting event.

Field discipline is in docs/architecture/security.md section 12: `detail` may
carry identifiers and reasons, never a credential, a token, a prompt, or a
completion.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.sqlalchemy_models import AuditLogRow
from app.domain.entities.actor import Actor
from app.shared.clock import Clock

logger = logging.getLogger(__name__)


class PostgresAudit:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def record(
        self,
        actor: Actor,
        action: str,
        *,
        target: str | None = None,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None:
        row = AuditLogRow(
            id=str(uuid.uuid4()),
            actor_id=actor.id,
            actor_display=actor.display,
            actor_source=actor.source,
            action=action,
            target=target,
            outcome=outcome,
            detail=detail or {},
            at=self._clock.now(),
        )

        try:
            async with self._sessions() as session:
                session.add(row)
                await session.commit()
        except Exception:
            # A failed audit write must not turn a successful administrative
            # action into a 500, and must not swallow the event silently
            # either. The application log is the fallback record; it is not
            # tamper-evident, which is why the database row is preferred, but
            # losing the event entirely is the worse outcome.
            logger.exception(
                "audit_write_failed action=%s actor=%s target=%s outcome=%s",
                action,
                actor.display,
                target,
                outcome,
            )
