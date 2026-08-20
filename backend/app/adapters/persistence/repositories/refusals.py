"""Persistence refusals boundary."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    RefusalRow,
)
from app.domain.entities.refusal import Refusal

from .shared import _TenantScoped

# Pinned rather than `__name__`: the formatter prints the logger name, and
# this line was emitted under the pre-split module before the package existed.
logger = logging.getLogger("app.adapters.persistence.repositories")


class PostgresRefusalWriter:
    """Appends a refusal in its own transaction.

    **Its own session, and here that is not an asymmetry but the only way it
    can work.** Every row this class writes is written from an exception
    handler, so the request's session is on its way to a rollback in every
    single case. `PostgresPromptLogWriter` learned this the hard way for a
    table where the failing request was the *interesting* one; for this table
    the failing request is the only one.

    Swallows and logs its own failures, unlike that class, which is guarded at
    its call site. There is no call site to guard: the caller is a handler
    rendering an error response, and an exception raised into it would replace
    the refusal the caller is owed with a 500 about the bookkeeping.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(self, refusal: Refusal) -> None:
        try:
            async with self._sessions() as session:
                session.add(m.refusal_to_row(refusal.truncated()))
                await session.commit()
        except Exception:  # noqa: BLE001
            # The code and the request id, and nothing else. This log line
            # exists so a missing row is explicable; repeating the message or
            # the figures here would put a copy of the caller-facing answer in
            # a log with ordinary retention, which is the trade the whole table
            # is arranged to avoid.
            logger.exception(
                "failed to record refusal code=%s request_id=%s", refusal.code, refusal.request_id
            )


class PostgresRefusalRepository(_TenantScoped):
    """Reading refusals, on the admin entrances only. The write is
    `PostgresRefusalWriter`, which needs a transaction of its own."""

    @staticmethod
    def _contains(needle: str) -> str:
        """A `LIKE` pattern matching `needle` anywhere, with its wildcards spent.

        `%` and `_` are wildcards in `LIKE`, so a login containing either would
        otherwise match more than itself — `a_b` would find `axb`, and a lone
        `%` typed into the box would match every row while looking like a
        narrowing. The backslash that does the escaping has to be escaped
        first, or escaping is what breaks the pattern.
        """
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def _filtered(
        self,
        stmt: Any,
        *,
        actor_id: str | None,
        actor_display: str | None,
        api_key_id: str | None,
        code: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Any:
        stmt = self._scope(stmt, RefusalRow.tenant_id)
        if actor_id:
            stmt = stmt.where(RefusalRow.actor_id == actor_id)
        if actor_display:
            # The only substring match on this table, and the only filter here
            # that is not an equality. It exists because the id is a uuid and
            # the name is the part a reader can see — and because it is what
            # still finds a deleted account's refusals, which is when somebody
            # is most likely to be looking. Narrowing further is the use case's
            # job: this is ANDed with the actor filter, so a reader confined to
            # their own stays confined whatever they type here.
            stmt = stmt.where(
                RefusalRow.actor_display.ilike(self._contains(actor_display), escape="\\")
            )
        if api_key_id:
            stmt = stmt.where(RefusalRow.api_key_id == api_key_id)
        if code:
            stmt = stmt.where(RefusalRow.code == code)
        if request_id:
            stmt = stmt.where(RefusalRow.request_id == request_id)
        if since is not None:
            stmt = stmt.where(RefusalRow.at >= since)
        if until is not None:
            stmt = stmt.where(RefusalRow.at < until)
        return stmt

    async def list_refusals(
        self,
        *,
        actor_id: str | None,
        actor_display: str | None,
        api_key_id: str | None,
        code: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[Refusal]:
        stmt = self._filtered(
            select(RefusalRow),
            actor_id=actor_id,
            actor_display=actor_display,
            api_key_id=api_key_id,
            code=code,
            request_id=request_id,
            since=since,
            until=until,
        )
        rows = await self._session.scalars(
            stmt.order_by(RefusalRow.at.desc(), RefusalRow.id.desc()).limit(limit).offset(offset)
        )
        return [m.refusal_row_to_domain(row) for row in rows]

    async def count_refusals(
        self,
        *,
        actor_id: str | None,
        actor_display: str | None,
        api_key_id: str | None,
        code: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int:
        stmt = self._filtered(
            select(func.count()).select_from(RefusalRow),
            actor_id=actor_id,
            actor_display=actor_display,
            api_key_id=api_key_id,
            code=code,
            request_id=request_id,
            since=since,
            until=until,
        )
        total = await self._session.scalar(stmt)
        return int(total or 0)
