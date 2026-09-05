"""Persistence observability retention boundary."""

from __future__ import annotations

from app.adapters.persistence.sqlalchemy_models import (
    AuditLogRow,
    PromptLogRow,
    PromptTemplateRow,
    RefusalRow,
    RetentionPolicyRow,
    UsageRecordRow,
)
from app.domain.entities.audit import AuditEntry
from app.domain.entities.prompt_log import PromptLogEntry
from app.domain.entities.prompt_template import PromptTemplate
from app.domain.entities.refusal import Refusal
from app.domain.entities.retention import RetentionDataset, RetentionPolicy
from app.domain.entities.usage import UsageRecord


def audit_row_to_domain(row: AuditLogRow) -> AuditEntry:
    # detail is JSON, so its values arrive as Any; coerce to str because the
    # entity and the response both promise str, and the writer only ever stores
    # strings. See adapters/audit/postgres_audit.py.
    return AuditEntry(
        id=row.id,
        actor_id=row.actor_id,
        actor_display=row.actor_display,
        actor_source=row.actor_source,
        action=row.action,
        target=row.target,
        outcome=row.outcome,
        detail={k: str(v) for k, v in (row.detail or {}).items()},
        at=row.at,
        tenant_id=row.tenant_id,
    )


def usage_to_row(usage: UsageRecord) -> UsageRecordRow:
    return UsageRecordRow(
        id=usage.id,
        tenant_id=usage.tenant_id,
        actor_id=usage.actor_id,
        api_key_id=usage.api_key_id,
        capability=usage.capability,
        requested_capability=usage.requested_capability,
        model_alias=usage.model_alias,
        tokens=usage.tokens,
        prompt_tokens=usage.prompt_tokens,
        latency_ms=usage.latency_ms,
        completed=usage.completed,
        at=usage.at,
        compaction_tier=usage.compaction_tier,
        tokens_before_compaction=usage.tokens_before_compaction,
        tokens_after_compaction=usage.tokens_after_compaction,
    )


def retention_row_to_domain(row: RetentionPolicyRow) -> RetentionPolicy:
    # `dataset` is validated on the way in — the use case takes a
    # `RetentionDataset` and the column is written from `.value` — so a row that
    # no longer matches the enum is a dataset that was removed from the code
    # while its row stayed. Constructing the enum here surfaces that as a
    # failure to read the policy rather than as a purge aimed at nothing.
    return RetentionPolicy(
        dataset=RetentionDataset(row.dataset),
        days=row.days,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def prompt_template_to_domain(row: PromptTemplateRow) -> PromptTemplate:
    return PromptTemplate(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def prompt_template_to_row(template: PromptTemplate) -> PromptTemplateRow:
    row = PromptTemplateRow(
        id=template.id,
        tenant_id=template.tenant_id,
        name=template.name,
        description=template.description,
        system_prompt=template.system_prompt,
    )
    # Server defaults supply both on insert; carried back only when the entity
    # already has them, so a save never blanks a timestamp it did not read.
    if template.created_at is not None:
        row.created_at = template.created_at
    if template.updated_at is not None:
        row.updated_at = template.updated_at
    return row


def prompt_log_to_row(entry: PromptLogEntry) -> PromptLogRow:
    return PromptLogRow(
        id=entry.id,
        tenant_id=entry.tenant_id,
        at=entry.at,
        actor_id=entry.actor_id,
        api_key_id=entry.api_key_id,
        capability=entry.capability,
        model_alias=entry.model_alias,
        request_id=entry.request_id,
        messages=entry.messages,
        completion=entry.completion,
        reasoning=entry.reasoning,
        finish_reason=entry.finish_reason,
        completed=entry.completed,
        tool_calls=entry.tool_calls,
        # Sorted, so two rows recording the same pair of capped fields are
        # byte-identical here. An unordered set serialised straight to JSON
        # would differ run to run and make a stored transcript look edited.
        truncated_fields=sorted(entry.truncated_fields),
    )


def prompt_log_row_to_domain(row: PromptLogRow) -> PromptLogEntry:
    return PromptLogEntry(
        id=row.id,
        at=row.at,
        actor_id=row.actor_id,
        api_key_id=row.api_key_id,
        capability=row.capability,
        model_alias=row.model_alias,
        request_id=row.request_id,
        messages=row.messages,
        completion=row.completion,
        reasoning=row.reasoning,
        finish_reason=row.finish_reason,
        completed=row.completed,
        tool_calls=row.tool_calls,
        tenant_id=row.tenant_id,
        # `str(v)` for the same reason `audit_row_to_domain` coerces its detail
        # values: the column is JSON, so it hands back Any, and the entity
        # promises a set of field names.
        truncated_fields=frozenset(str(v) for v in (row.truncated_fields or [])),
    )


def refusal_to_row(refusal: Refusal) -> RefusalRow:
    return RefusalRow(
        id=refusal.id,
        tenant_id=refusal.tenant_id,
        at=refusal.at,
        actor_id=refusal.actor_id,
        actor_display=refusal.actor_display,
        api_key_id=refusal.api_key_id,
        code=refusal.code,
        status=refusal.status,
        surface=refusal.surface,
        method=refusal.method,
        path=refusal.path,
        request_id=refusal.request_id,
        message=refusal.message,
        figures=dict(refusal.figures),
    )


def refusal_row_to_domain(row: RefusalRow) -> Refusal:
    return Refusal(
        id=row.id,
        at=row.at,
        code=row.code,
        status=row.status,
        actor_id=row.actor_id,
        # Empty on a row written before this column existed, which reads as
        # "unknown" rather than failing the page it appears on.
        actor_display=row.actor_display or "",
        api_key_id=row.api_key_id,
        surface=row.surface,
        method=row.method,
        path=row.path,
        request_id=row.request_id,
        message=row.message,
        # Coerced, for the reason the prompt-log mapper coerces its own JSON
        # column: a row written before this column existed reads back as None,
        # and a `None` where a mapping is declared fails far from here.
        figures=dict(row.figures or {}),
        tenant_id=row.tenant_id,
    )
