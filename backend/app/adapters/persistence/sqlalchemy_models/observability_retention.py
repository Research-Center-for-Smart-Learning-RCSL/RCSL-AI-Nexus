"""Persistence observability retention boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UsageRecordRow(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    """No foreign key, matching `api_key_id` below: this table stays free of
    them so a record survives the deletion of anything it names. The tenant is
    stamped from an already-authenticated actor, so integrity holds at the
    application layer."""

    actor_id: Mapped[str] = mapped_column(String(36), index=True)

    api_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Holds `ApiKey.key_id`, the public handle, not the row's UUID. Chosen so
    the record survives the key being deleted, which is also why there is no
    foreign key. Sized for a 16-character handle rather than a UUID; the
    previous width made the ambiguity easy to miss."""

    capability: Mapped[str] = mapped_column(String(64))
    requested_capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """What the caller sent, when a key's `default_capability` made it differ
    from the capability that served. Null when the two agree, which is every
    row written before the column existed — so null means "the same", not
    "unknown", and nothing already stored is reinterpreted.

    Not indexed. The question it answers ("is this key being defaulted, and
    what is its client sending?") is asked of one key at a time, and
    `ix_usage_key_at` already narrows that to a handful of rows."""
    model_alias: Mapped[str] = mapped_column(String(128))
    tokens: Mapped[int] = mapped_column(Integer)
    """Tokens generated. Still means only that after `prompt_tokens` arrived,
    so historical rows are not silently reinterpreted as totals."""

    prompt_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    """Tokens read. `server_default` rather than a Python default so the
    backfill of existing rows is the migration's job and not every writer's;
    every row written before 2026-08-04 is genuinely zero, because nothing
    counted them."""

    latency_ms: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        # The quota reads by key over a time window, so the composite is what
        # that query actually needs.
        Index("ix_usage_key_at", "api_key_id", "at"),
    )


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    """The tenant of the actor who performed the action, so a future per-tenant
    logs view can filter to it. No foreign key, keeping this append-only table
    free of them."""

    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_display: Mapped[str] = mapped_column(String(255))
    actor_source: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    """Append-only except through retention.

    It was append-only outright until 2026-08-04, when a `retention:write`
    holder gained the ability to set a window and to purge ahead of it. The
    gateway still cannot touch this table at all — its account holds `INSERT`
    on `usage_records` and nothing else (`db_roles.py`), which is the guarantee
    that actually constrains the untrusted side. What changed is that the
    administrator's own account, which always had `DELETE` here, now has a
    supported path to it. See `security.md` §12.1.
    """


class RetentionPolicyRow(Base):
    """One row per dataset, written the first time somebody sets it.

    The absence of a row means the default in `domain/entities/retention.py`,
    which is why there is no migration seeding one: a seeded default is a
    decision nobody made, wearing the name of whoever ran the migration.
    """

    __tablename__ = "retention_policies"

    dataset: Mapped[str] = mapped_column(String(32), primary_key=True)
    days: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(255))
    """Display name rather than an id, and denormalised on purpose: the row has
    to stay readable after the account that set it is deleted, which is the
    same reason `audit_log` stores one."""


class PromptTemplateRow(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    """Tenant data, like a knowledge collection and unlike a model: a template
    is text a team wrote, and it can encode how they work."""

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(1024), default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Per tenant, for the reason the collections index gives: the name is
        # what a caller writes in `"prompt_template": "..."`, so it has to be
        # unique where that request is resolved, and no wider — a global
        # constraint would report that another tenant had taken a name.
        Index("ix_prompt_templates_tenant_name", "tenant_id", "name", unique=True),
    )


class PromptLogRow(Base):
    """Full prompt and completion text, written only while a debug window is
    open (security.md section 9.2, `domain/entities/prompt_log.py`).

    **Every text column here is `Text`, and that is a security property rather
    than a sizing preference.** `audit_log` used `String(n)` and lost rows
    whose values were wider — silently, so that padding a URL suppressed the
    record of probing it (PROGRESS.md 2026-08-02). A transcript is the widest
    value this schema ever stores, so the same mistake here would drop exactly
    the rows an operator opened the window to read. The bound on this table is
    time, applied by the retention sweep, plus a per-field cap applied in the
    domain that *records that it applied* rather than trimming quietly.

    **No foreign keys**, like `audit_log` and for the same reason: the row must
    survive the deletion of the key or account it names. It is also the one
    table the gateway may write and may not read (`db_roles.py`), and a foreign
    key would give it a reason to need `SELECT` elsewhere.
    """

    __tablename__ = "prompt_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    api_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    capability: Mapped[str] = mapped_column(String(64))
    model_alias: Mapped[str] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """Indexed because it is the way in. A caller reports a failure by quoting
    the request id from their error envelope, and finding that conversation is
    the reason the window was opened."""

    messages: Mapped[str] = mapped_column(Text)
    completion: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")

    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    truncated_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    """Which fields hit the per-field cap. JSON rather than a flag, so the row
    says *which* half was cut — a capped prompt and a capped answer send a
    reader to different places."""

    __table_args__ = (
        # The paged read is "this tenant's transcripts, newest first", so the
        # index carries the filter and the sort together. Without the composite
        # the planner sorts the whole tenant partition on every page.
        Index("ix_prompt_logs_tenant_at", "tenant_id", "at"),
    )


class RefusalRow(Base):
    """What a caller was refused, kept where they can read it back.

    **Not a second copy of the application log.** What is stored is what left
    the process: the code, the status, the message the caller received and the
    figures that accompanied it. `detail` is absent by construction — the
    handler builds this from the same function that builds the response body —
    which is what makes a row here safe to show its own subject.

    **No foreign keys**, like `audit_log` and `prompt_logs`. The row must
    survive the deletion of the key or the account it names, and the gateway
    writes here with an account that has no reason to hold `SELECT` anywhere
    else.

    Text columns are `Text`, not `String(n)`, for the reason `prompt_logs`
    gives: `audit_log` lost rows whose values were wider than their column, and
    lost them silently. The bound here is time, applied by the retention sweep,
    plus a per-figure cap in the domain that records that it applied.
    """

    __tablename__ = "refusals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_display: Mapped[str] = mapped_column(String(255), default="")
    """Denormalised like `audit_log`'s, so the row stays readable after the
    account is gone and a page of other people's refusals says whose."""

    api_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    code: Mapped[str] = mapped_column(String(64), index=True)
    """Indexed because it is what an operator filters by. A status is too
    coarse: the evening this table exists for had two 413s with different causes
    and two 409s with nothing in common."""

    status: Mapped[int] = mapped_column(Integer)
    surface: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """Indexed because it is the way in. A caller reports a failure by quoting
    the id from their error envelope."""

    message: Mapped[str] = mapped_column(Text)
    figures: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        # The paged read is "this tenant's refusals, newest first", and the
        # commonest filtered read is one actor's. Both sort by `at`, so the
        # index carries the filter and the sort together — without it the
        # planner sorts the whole tenant partition on every page.
        Index("ix_refusals_tenant_at", "tenant_id", "at"),
        Index("ix_refusals_actor_at", "actor_id", "at"),
    )
