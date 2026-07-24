"""ORM models.

Deliberately separate from the domain entities in `app/domain/entities/`.
Persistence concerns (column types, indexes, cascade rules) and business
concerns evolve for different reasons, and merging them would put SQLAlchemy
imports inside the layer that must stay framework-free. Repository adapters
translate between the two.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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

    __table_args__ = (
        # A runtime identifier is unique per node, unlike the alias which is
        # unique platform-wide.
        Index("ix_models_node_ref", "node_id", "runtime", "ref", unique=True),
    )


class RoutingPolicyRow(Base):
    __tablename__ = "routing_policies"

    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidates: Mapped[list[dict]] = mapped_column(JSON, default=list)
    """Structured requirement documents, never expression strings. See
    docs/ARCHITECTURE.md section 2.4 for why this distinction matters."""


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    login: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))

    tailscale_login: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # Both nullable: a tailnet-only user never needs local credentials, and an
    # invited user has none until they complete the invitation.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    debug_logging_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvitationRow(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    """Only the hash is stored; the plaintext exists once, in the link."""

    purpose: Mapped[str] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryCodeRow(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(128))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    debug_logging_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UsageRecordRow(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    capability: Mapped[str] = mapped_column(String(64))
    model_alias: Mapped[str] = mapped_column(String(128))
    tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_display: Mapped[str] = mapped_column(String(255))
    actor_source: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    """Append-only by convention and by the migration account's grants; there
    is no update or delete path in any repository."""
