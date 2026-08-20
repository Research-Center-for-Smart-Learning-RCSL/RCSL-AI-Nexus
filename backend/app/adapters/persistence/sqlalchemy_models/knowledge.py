"""Persistence knowledge boundary."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
