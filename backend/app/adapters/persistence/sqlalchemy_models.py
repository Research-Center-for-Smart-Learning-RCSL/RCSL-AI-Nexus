"""ORM models.

Deliberately separate from the domain entities in `app/domain/entities/`.
Persistence concerns (column types, indexes, cascade rules) and business
concerns evolve for different reasons, and merging them would put SQLAlchemy
imports inside the layer that must stay framework-free. Repository adapters
translate between the two.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NodeRow(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))
    total_memory_gb: Mapped[float] = mapped_column(Float)
    runtimes: Mapped[list[str]] = mapped_column(JSON, default=list)


class ModelRow(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alias: Mapped[str] = mapped_column(String(128), unique=True)
    """Routing policies bind to this, so it is globally unique."""

    ref: Mapped[str] = mapped_column(String(255))
    runtime: Mapped[str] = mapped_column(String(16))
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("nodes.id"))
    state: Mapped[str] = mapped_column(String(24))
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    memory_gb: Mapped[float] = mapped_column(Float, default=0.0)
    context_length: Mapped[int] = mapped_column(Integer, default=0)

    # What the runtime last reported, written by the heartbeat; `state` above
    # is intent. All nullable: null means never observed, which is also what a
    # runtime with no residency endpoint (MLX) leaves behind.
    observed_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    observed_memory_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # A runtime identifier is unique per node, unlike the alias which is
        # unique platform-wide.
        Index("ix_models_node_ref", "node_id", "runtime", "ref", unique=True),
    )


class RoutingPolicyRow(Base):
    __tablename__ = "routing_policies"

    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    """Structured requirement documents, never expression strings. See
    docs/ARCHITECTURE.md section 2.4 for why this distinction matters."""

    thinking: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    """Nullable on purpose: three states, not two. NULL is "this policy has no
    opinion, use the deployment default", which is what every policy written
    before this column existed means and what a boolean with a default could
    not express."""


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    login: Mapped[str] = mapped_column(String(255), unique=True)
    """Globally unique, not per-tenant. Authentication resolves a login before
    any tenant is known, so a login names exactly one account across the whole
    platform and its tenant is then read from the row."""

    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))

    tailscale_login: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # Both nullable: a tailnet-only user never needs local credentials, and an
    # invited user has none until they complete the invitation.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    debug_logging_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # "An account never exists in a password-only state" was enforced only
        # by a Python property, so a direct write or a half-finished invitation
        # could produce the state the design says is impossible. Enforced here
        # instead, where a second writer cannot get around it.
        CheckConstraint(
            "(password_hash IS NULL) = (totp_secret IS NULL)",
            name="ck_users_password_implies_totp",
        ),
    )


class InvitationRow(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    """Only the hash is stored; the plaintext exists once, in the link."""

    purpose: Mapped[str] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_invitations_user_purpose", "user_id", "purpose"),)


class RecoveryCodeRow(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    key_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    """Independent random lookup handle, not a prefix of the secret, so
    nothing secret reaches logs or indexes."""

    digest: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_cidrs: Mapped[list[str]] = mapped_column(JSON, default=list)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    quota_tokens_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    default_capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Nullable, and null is the behaviour every key had before the column
    existed: a capability this key was not issued for is refused. A name here
    is served instead, and `ManageApiKeys` will only store one that is already
    in `scopes`. No foreign key and no enum — the issuable set is a domain
    constant (`domain/entities/capability.py`), and a second copy of it in the
    schema is the drift that constant exists to end."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """NOT NULL, because `is_active` reads a null expiry as "never expires".
    The docs call expiry mandatory and the entity comment claimed a use case
    enforced it; a nullable column meant one direct insert or import produced a
    permanently valid key with rotation bypassed."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    """There is deliberately no `last_used_at` beside this. Maintaining one
    would mean the gateway writing to this table on every request, and the
    account split in security.md section 6 exists so that it cannot. The same
    fact is derived from `usage_records`, which the gateway does write."""

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    debug_logging_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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


class KnowledgeCollectionRow(Base):
    __tablename__ = "knowledge_collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    """Unlike `models` and `nodes`, which are the shared compute, a collection is
    tenant data: it holds the team's unpublished research (security.md 9.1)."""

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Unique per tenant, not globally: two tenants naming a collection
        # "Papers" is ordinary, and a global constraint would leak the fact that
        # another tenant had taken the name.
        Index("ix_knowledge_collections_tenant_name", "tenant_id", "name", unique=True),
    )


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_collections.id"), index=True
    )
    """The tenant is carried here as well as on the collection, and the
    redundancy is deliberate: every scoped read filters on this column directly,
    so a document query never has to join to be correctly scoped."""

    filename: Mapped[str] = mapped_column(String(255))
    """The uploader's name for the file, sanitised for display. No storage path
    is derived from it; keys come from `id`. See adapters/storage/."""

    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(16), index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    uploaded_by: Mapped[str] = mapped_column(String(36))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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


class EvaluationRunRow(Base):
    """One execution of the capability task set.

    Platform-global like `models` and `nodes`, and for the same reason: it
    describes the fleet rather than anyone's content, so it carries no
    `tenant_id`. Every tenant that can see the models can see what they scored.
    """

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), unique=True)
    """Unique, and that is what makes re-importing a correction rather than a
    duplicate. A run gets re-imported — the 2026-08-15 figures were themselves
    corrected after three prompts were found to be measuring their own
    formatting — and two rows of the same run on one screen is the failure this
    constraint exists to prevent."""

    phase: Mapped[str] = mapped_column(String(32))
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    """Indexed because the only ordering this table is ever read in is newest
    first, and "what is the current reading" is the question the screen opens
    with."""

    harness_ref: Mapped[str] = mapped_column(String(255), default="")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    caveats: Mapped[list[str]] = mapped_column(JSON, default=list)
    """What the run does not establish. JSON rather than a `Text` blob so the
    screen renders them as the list they are, and stored per run rather than
    written into the page, because the next run's caveats are different ones."""

    note: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    imported_by: Mapped[str] = mapped_column(String(255), default="")
    """Display name, denormalised for the reason `retention_policies` stores
    one: the row outlives the account."""


class EvaluationModelScoreRow(Base):
    """One model's whole result in one run."""

    __tablename__ = "evaluation_model_scores"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    """Wider than the 36 a UUID needs, because it is not one: the writer builds
    it as `<run id>:m<index>` so that ordering by id is ordering by the
    aggregate's own sequence. A plain UUID would need a sort column beside it
    that means the same thing."""
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    """Cascading, unlike most foreign keys here. These rows are derived from
    the run and mean nothing without it, so deleting a run must not be able to
    leave scores behind that no screen can reach and no query will find."""

    model_ref: Mapped[str] = mapped_column(String(128))
    """The runtime reference the harness ran (`qwen3.6:35b-a3b-q8_0`), not a
    registry alias. An alias is a name an operator may reassign to different
    weights; what was measured was the weights."""

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_samples: Mapped[int] = mapped_column(Integer, default=0)
    no_result_samples: Mapped[int] = mapped_column(Integer, default=0)
    generation_tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_depth_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seconds_per_round_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    seconds_per_round_max: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvaluationTaskScoreRow(Base):
    """One model's mean on one task, which is where the verdicts come from."""

    __tablename__ = "evaluation_task_scores"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    """`<run id>:t<index>`, zero-padded, for the reason above."""
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    model_ref: Mapped[str] = mapped_column(String(128))
    task: Mapped[str] = mapped_column(String(64))
    task_group: Mapped[str] = mapped_column(String(8))
    """The harness's group letter. Named `task_group` rather than `group`
    because the bare word is reserved in SQL: SQLAlchemy quotes it, and the
    first hand-written query against this table would not."""

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # The read is always "every task score for this run", assembled into a
        # grid, so the run is the filter and the pair below is the sort.
        Index("ix_evaluation_task_scores_run_task", "run_id", "task", "model_ref"),
    )
