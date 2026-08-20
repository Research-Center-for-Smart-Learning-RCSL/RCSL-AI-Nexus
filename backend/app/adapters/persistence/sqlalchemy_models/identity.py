"""Persistence identity boundary."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
