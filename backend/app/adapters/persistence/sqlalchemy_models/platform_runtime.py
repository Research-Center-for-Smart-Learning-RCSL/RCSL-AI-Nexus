"""Persistence platform runtime boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
