"""Persistence audit boundary."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    AuditLogRow,
)
from app.domain.entities.audit import AuditEntry

from .shared import _TenantScoped

logger = logging.getLogger(__name__)


class PostgresAuditLogRepository(_TenantScoped):
    """Read side of the audit log, tenant-scoped like every other read. The
    write side (`PostgresAudit`) uses its own transaction; this does not, because
    reading is an ordinary request-session query."""

    def _filtered(
        self,
        stmt: Any,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Any:
        stmt = self._scope(stmt, AuditLogRow.tenant_id)
        if action:
            stmt = stmt.where(AuditLogRow.action == action)
        if outcome:
            stmt = stmt.where(AuditLogRow.outcome == outcome)
        if actor_id:
            stmt = stmt.where(AuditLogRow.actor_id == actor_id)
        if since is not None:
            stmt = stmt.where(AuditLogRow.at >= since)
        if until is not None:
            stmt = stmt.where(AuditLogRow.at < until)
        return stmt

    async def list_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[AuditEntry]:
        stmt = self._filtered(
            select(AuditLogRow),
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        # Newest first: an operator reads the most recent action, and the pager
        # walks backwards through history.
        stmt = stmt.order_by(AuditLogRow.at.desc()).limit(limit).offset(offset)
        rows = await self._session.scalars(stmt)
        return [m.audit_row_to_domain(row) for row in rows]

    async def count_entries(
        self,
        *,
        action: str | None,
        outcome: str | None,
        actor_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int:
        stmt = self._filtered(
            select(func.count()).select_from(AuditLogRow),
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            since=since,
            until=until,
        )
        total = await self._session.scalar(stmt)
        return int(total or 0)
