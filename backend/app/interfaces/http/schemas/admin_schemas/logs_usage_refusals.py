"""Admin logs usage refusals schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.application.use_cases.read_audit_log import AuditLogPage
from app.application.use_cases.read_prompt_logs import PromptLogPage
from app.application.use_cases.read_refusals import RefusalPage
from app.application.use_cases.read_usage_analytics import UsageAnalytics
from app.application.use_cases.read_usage_records import UsageRecordPage
from app.domain.entities.audit import AuditEntry
from app.domain.entities.prompt_log import PromptLogEntry, PromptLogSummary
from app.domain.entities.refusal import Refusal
from app.domain.entities.usage import UsageRecord


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
    compaction_tier: int | None

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
            compaction_tier=entry.compaction_tier,
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
    compaction_tier: int | None
    """Which tier reduced `messages` below, or None.

    This response is the reason the column exists. Everywhere else a reader
    sees counts; here they see the prompt itself, and after a compaction that
    prompt is not the one the caller composed. A transcript that showed the
    reduced conversation with nothing saying so would be the quietest place in
    the platform for the reduction to hide.
    """

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
            compaction_tier=entry.compaction_tier,
            messages=entry.messages,
            completion=entry.completion,
            reasoning=entry.reasoning,
        )


class UsageRecordResponse(BaseModel):
    """One served request, in the shape the row was written.

    Carries no prompt and no completion — this table never held either. That is
    what makes it the general per-request surface: `prompt_logs` holds the text
    and exists only while a debug window is open, so it can answer "what was
    said" for a few requests and never "what happened" for all of them.
    """

    id: str
    at: datetime
    actor_id: str
    api_key_id: str | None
    capability: str
    requested_capability: str | None
    model_alias: str
    tokens: int
    prompt_tokens: int
    latency_ms: int
    completed: bool
    compaction_tier: int | None
    tokens_before_compaction: int | None
    tokens_after_compaction: int | None

    @classmethod
    def of(cls, record: UsageRecord) -> UsageRecordResponse:
        return cls(
            id=record.id,
            at=record.at,
            actor_id=record.actor_id,
            api_key_id=record.api_key_id,
            capability=record.capability,
            requested_capability=record.requested_capability,
            model_alias=record.model_alias,
            tokens=record.tokens,
            prompt_tokens=record.prompt_tokens,
            latency_ms=record.latency_ms,
            completed=record.completed,
            compaction_tier=record.compaction_tier,
            tokens_before_compaction=record.tokens_before_compaction,
            tokens_after_compaction=record.tokens_after_compaction,
        )


class UsageRecordListResponse(BaseModel):
    entries: list[UsageRecordResponse]
    total: int
    limit: int
    offset: int
    scoped_to_self: bool
    """True when the reader may see only their own requests, so the screen can
    say so instead of showing an actor filter that silently does nothing."""

    @classmethod
    def of(cls, page: UsageRecordPage) -> UsageRecordListResponse:
        return cls(
            entries=[UsageRecordResponse.of(e) for e in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            scoped_to_self=page.scoped_to_self,
        )


class UsagePointResponse(BaseModel):
    t: datetime
    requests: int
    tokens: int


class CapabilitySeriesResponse(BaseModel):
    capability: str
    points: list[UsagePointResponse]


class CompactionTierCountResponse(BaseModel):
    tier: int
    requests: int


class CompactionSummaryResponse(BaseModel):
    """Compaction over the same window as the charts beside it.

    `requests` counts requests whose prompt was reduced, not requests through a
    key that allows it — the second is not a number this platform tracks and
    would not be a ratio worth showing if it were.
    """

    requests: int
    tokens_removed: int
    by_tier: list[CompactionTierCountResponse]


class UsageAnalyticsResponse(BaseModel):
    bucket: str
    since: datetime
    until: datetime
    totals: list[UsagePointResponse]
    by_capability: list[CapabilitySeriesResponse]
    compaction: CompactionSummaryResponse

    @classmethod
    def of(cls, analytics: UsageAnalytics) -> UsageAnalyticsResponse:
        return cls(
            bucket=analytics.bucket,
            since=analytics.since,
            until=analytics.until,
            compaction=CompactionSummaryResponse(
                requests=analytics.compaction.requests,
                tokens_removed=analytics.compaction.tokens_removed,
                by_tier=[
                    CompactionTierCountResponse(tier=t.tier, requests=t.requests)
                    for t in analytics.compaction.by_tier
                ],
            ),
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
