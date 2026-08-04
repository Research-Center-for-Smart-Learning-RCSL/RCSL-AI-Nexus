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
    """Append-only by convention and by the migration account's grants; there
    is no update or delete path in any repository."""
