"""Persistence prompt logs boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    PromptLogRow,
)
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary

from .shared import _TenantScoped


class PostgresPromptLogWriter:
    """Appends a transcript in its own transaction, like `PostgresAudit`.

    **Its own session, and that is the whole point of the class.** The obvious
    implementation is `session.add` on the request's session, next to
    `PostgresUsageRepository.record`, and it was that for half a day. The
    argument was that a transcript belongs to a request that succeeded far
    enough to produce one, so sharing the transaction is right — which is
    exactly backwards for the case this feature exists to serve.

    A debug window is opened because a caller reported an error. When the
    generation then fails, the exception propagates out of `session_scope`,
    which rolls back, and the transcript goes with it: every successful request
    around it recorded fine, and the one conversation somebody was looking for
    was never written. An operator quoting a request id would find nothing and
    have no way to tell "the window was shut" from "the request failed".

    Committing separately means a transcript can outlive a rolled-back request,
    which is the intended asymmetry and the same one the audit log has. The
    write is best-effort at the call site (`RouteChatRequest` swallows and logs)
    so a failure here still cannot cost the answer or the usage record.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(self, entry: PromptLogEntry) -> None:
        # No tenant argument, unlike the reader. The tenant is on the entity,
        # put there by `TranscriptBuffer.build` from the resolved actor, which
        # is the same route usage takes on the gateway — where the repository
        # is unscoped and stamps from the record. A tenant parameter here would
        # be a second source for one value.
        async with self._sessions() as session:
            session.add(m.prompt_log_to_row(entry))
            await session.commit()


class PostgresPromptLogRepository(_TenantScoped):
    """Reading transcripts, on the admin entrances only. The write is
    `PostgresPromptLogWriter`, which needs a transaction of its own."""

    async def get(self, entry_id: str) -> PromptLogEntry | None:
        # Scoped through the same `_scope` as the list, rather than a bare
        # `session.get`. A primary-key fetch is exactly where a tenant boundary
        # is easiest to forget, and an id from another tenant must read as
        # absent rather than as forbidden.
        row = await self._session.scalar(
            self._scope(
                select(PromptLogRow).where(PromptLogRow.id == entry_id),
                PromptLogRow.tenant_id,
            )
        )
        return m.prompt_log_row_to_domain(row) if row else None

    def _filtered(
        self,
        stmt: Any,
        *,
        actor_id: str | None,
        api_key_id: str | None,
        capability: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Any:
        stmt = self._scope(stmt, PromptLogRow.tenant_id)
        if actor_id:
            stmt = stmt.where(PromptLogRow.actor_id == actor_id)
        if api_key_id:
            stmt = stmt.where(PromptLogRow.api_key_id == api_key_id)
        if capability:
            stmt = stmt.where(PromptLogRow.capability == capability)
        if request_id:
            stmt = stmt.where(PromptLogRow.request_id == request_id)
        if since is not None:
            stmt = stmt.where(PromptLogRow.at >= since)
        if until is not None:
            stmt = stmt.where(PromptLogRow.at < until)
        return stmt

    async def list_summaries(
        self,
        *,
        actor_id: str | None,
        api_key_id: str | None,
        capability: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> list[PromptLogSummary]:
        # The three text columns are never named here. `char_length` is
        # computed by Postgres and only the integer crosses the wire, so a page
        # of fifty transcripts costs kilobytes instead of hundreds of megabytes
        # — and, more to the point, the content is not in this process at all
        # for a request that only asked which conversations exist.
        stmt = self._filtered(
            select(
                PromptLogRow.id,
                PromptLogRow.at,
                PromptLogRow.tenant_id,
                PromptLogRow.actor_id,
                PromptLogRow.api_key_id,
                PromptLogRow.capability,
                PromptLogRow.model_alias,
                PromptLogRow.request_id,
                PromptLogRow.finish_reason,
                PromptLogRow.completed,
                PromptLogRow.tool_calls,
                PromptLogRow.truncated_fields,
                func.char_length(PromptLogRow.messages).label("message_chars"),
                func.char_length(PromptLogRow.completion).label("completion_chars"),
                func.char_length(PromptLogRow.reasoning).label("reasoning_chars"),
            ),
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            request_id=request_id,
            since=since,
            until=until,
        )
        stmt = stmt.order_by(PromptLogRow.at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).all()
        return [
            PromptLogSummary(
                id=row.id,
                at=row.at,
                tenant_id=row.tenant_id,
                actor_id=row.actor_id,
                api_key_id=row.api_key_id,
                capability=row.capability,
                model_alias=row.model_alias,
                request_id=row.request_id,
                finish_reason=row.finish_reason,
                completed=row.completed,
                tool_calls=row.tool_calls,
                message_chars=int(row.message_chars or 0),
                completion_chars=int(row.completion_chars or 0),
                reasoning_chars=int(row.reasoning_chars or 0),
                truncated_fields=frozenset(str(v) for v in (row.truncated_fields or [])),
            )
            for row in rows
        ]

    async def count_entries(
        self,
        *,
        actor_id: str | None,
        api_key_id: str | None,
        capability: str | None,
        request_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> int:
        stmt = self._filtered(
            select(func.count()).select_from(PromptLogRow),
            actor_id=actor_id,
            api_key_id=api_key_id,
            capability=capability,
            request_id=request_id,
            since=since,
            until=until,
        )
        total = await self._session.scalar(stmt)
        return int(total or 0)
