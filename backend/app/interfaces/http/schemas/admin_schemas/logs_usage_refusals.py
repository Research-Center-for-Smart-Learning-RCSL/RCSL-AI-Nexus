"""Admin logs usage refusals schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.application.use_cases.read_audit_log import AuditLogPage
from app.application.use_cases.read_prompt_logs import PromptLogPage
from app.application.use_cases.read_refusals import RefusalPage
from app.application.use_cases.read_usage_analytics import UsageAnalytics
from app.domain.entities.audit import AuditEntry
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary
from app.domain.entities.refusal import Refusal


class AuditEntryResponse(BaseModel):
    id: str
    actor_id: str
    actor_display: str
    actor_source: str
    action: str
    target: str | None
    outcome: str
    detail: dict[str, str]
    at: datetime

    @classmethod
    def of(cls, entry: AuditEntry) -> AuditEntryResponse:
        return cls(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_display=entry.actor_display,
            actor_source=entry.actor_source,
            action=entry.action,
            target=entry.target,
            outcome=entry.outcome,
            detail=entry.detail,
            at=entry.at,
        )


class AuditLogResponse(BaseModel):
    entries: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: AuditLogPage) -> AuditLogResponse:
        return cls(
            entries=[AuditEntryResponse.of(e) for e in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class PromptLogSummaryResponse(BaseModel):
    """A captured conversation, described but not disclosed.

    Carries no `messages`, `completion` or `reasoning`. The list exists to let
    an operator find the one conversation they need; reading it is a separate
    request that writes an audit row. The character counts are what a row is
    chosen by when the content is absent — an empty completion on a `stop`
    finish, or a prompt an order of magnitude larger than its neighbours, is
    visible from the table.
    """

    id: str
    at: datetime
    actor_id: str
    api_key_id: str | None
    capability: str
    model_alias: str
    request_id: str | None
    finish_reason: str | None
    completed: bool
    tool_calls: int
    message_chars: int
    completion_chars: int
    reasoning_chars: int
    truncated_fields: list[str]

    @classmethod
    def of(cls, entry: PromptLogSummary) -> PromptLogSummaryResponse:
        return cls(
            id=entry.id,
            at=entry.at,
            actor_id=entry.actor_id,
            api_key_id=entry.api_key_id,
            capability=entry.capability,
            model_alias=entry.model_alias,
            request_id=entry.request_id,
            finish_reason=entry.finish_reason,
            completed=entry.completed,
            tool_calls=entry.tool_calls,
            message_chars=entry.message_chars,
            completion_chars=entry.completion_chars,
            reasoning_chars=entry.reasoning_chars,
            truncated_fields=sorted(entry.truncated_fields),
        )


class RefusalResponse(BaseModel):
    """One refusal, in the shape the caller was refused in.

    Every field here was already sent to whoever provoked it — the code they
    branched on, the status, the message they read, and the figures that came
    with it. There is no second, fuller read behind this one, unlike the prompt
    logs above: the row *is* the disclosure, and it discloses a copy of an
    answer its subject already has.
    """

    id: str
    at: datetime
    code: str
    status: int
    actor_id: str
    actor_display: str
    api_key_id: str | None
    surface: str
    method: str
    path: str
    request_id: str | None
    message: str
    figures: dict[str, Any]

    @classmethod
    def of(cls, refusal: Refusal) -> RefusalResponse:
        return cls(
            id=refusal.id,
            at=refusal.at,
            code=refusal.code,
            status=refusal.status,
            actor_id=refusal.actor_id,
            actor_display=refusal.actor_display,
            api_key_id=refusal.api_key_id,
            surface=refusal.surface,
            method=refusal.method,
            path=refusal.path,
            request_id=refusal.request_id,
            message=refusal.message,
            figures=refusal.figures,
        )


class RefusalListResponse(BaseModel):
    entries: list[RefusalResponse]
    total: int
    limit: int
    offset: int
    scoped_to_self: bool
    """True when the reader may see only their own, so the screen can say so
    rather than presenting a filter that silently does nothing."""

    @classmethod
    def of(cls, page: RefusalPage) -> RefusalListResponse:
        return cls(
            entries=[RefusalResponse.of(e) for e in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            scoped_to_self=page.scoped_to_self,
        )


class PromptLogListResponse(BaseModel):
    entries: list[PromptLogSummaryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: PromptLogPage) -> PromptLogListResponse:
        return cls(
            entries=[PromptLogSummaryResponse.of(e) for e in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class PromptLogTranscriptResponse(BaseModel):
    """The full conversation. The only response in this file that carries
    message content, and the only read that writes an audit row."""

    id: str
    at: datetime
    actor_id: str
    api_key_id: str | None
    capability: str
    model_alias: str
    request_id: str | None
    finish_reason: str | None
    completed: bool
    tool_calls: int
    truncated_fields: list[str]
    messages: str
    completion: str
    reasoning: str

    @classmethod
    def of(cls, entry: PromptLogEntry) -> PromptLogTranscriptResponse:
        return cls(
            id=entry.id,
            at=entry.at,
            actor_id=entry.actor_id,
            api_key_id=entry.api_key_id,
            capability=entry.capability,
            model_alias=entry.model_alias,
            request_id=entry.request_id,
            finish_reason=entry.finish_reason,
            completed=entry.completed,
            tool_calls=entry.tool_calls,
            truncated_fields=sorted(entry.truncated_fields),
            messages=entry.messages,
            completion=entry.completion,
            reasoning=entry.reasoning,
        )


class UsagePointResponse(BaseModel):
    t: datetime
    requests: int
    tokens: int


class CapabilitySeriesResponse(BaseModel):
    capability: str
    points: list[UsagePointResponse]


class UsageAnalyticsResponse(BaseModel):
    bucket: str
    since: datetime
    until: datetime
    totals: list[UsagePointResponse]
    by_capability: list[CapabilitySeriesResponse]

    @classmethod
    def of(cls, analytics: UsageAnalytics) -> UsageAnalyticsResponse:
        return cls(
            bucket=analytics.bucket,
            since=analytics.since,
            until=analytics.until,
            totals=[
                UsagePointResponse(t=p.at, requests=p.requests, tokens=p.tokens)
                for p in analytics.totals
            ],
            by_capability=[
                CapabilitySeriesResponse(
                    capability=s.capability,
                    points=[
                        UsagePointResponse(t=p.at, requests=p.requests, tokens=p.tokens)
                        for p in s.points
                    ],
                )
                for s in analytics.by_capability
            ],
        )
