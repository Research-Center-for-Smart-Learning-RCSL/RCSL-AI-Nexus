"""Persistence knowledge boundary."""

from __future__ import annotations

from app.adapters.persistence.sqlalchemy_models import (
    KnowledgeCollectionRow,
    KnowledgeDocumentRow,
)
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)


def collection_to_domain(
    row: KnowledgeCollectionRow, document_count: int = 0
) -> KnowledgeCollection:
    """`document_count` is passed in rather than read off the row: it is an
    aggregate the repository computes, not a stored column that could drift."""
    return KnowledgeCollection(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        document_count=document_count,
        created_at=row.created_at,
    )


def collection_to_row(collection: KnowledgeCollection) -> KnowledgeCollectionRow:
    return KnowledgeCollectionRow(
        id=collection.id,
        tenant_id=collection.tenant_id,
        name=collection.name,
        description=collection.description,
    )


def document_to_domain(row: KnowledgeDocumentRow) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=row.id,
        tenant_id=row.tenant_id,
        collection_id=row.collection_id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        status=DocumentStatus(row.status),
        chunk_count=row.chunk_count,
        error=row.error,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
    )


def document_to_row(document: KnowledgeDocument) -> KnowledgeDocumentRow:
    return KnowledgeDocumentRow(
        id=document.id,
        tenant_id=document.tenant_id,
        collection_id=document.collection_id,
        filename=document.filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        status=document.status.value,
        chunk_count=document.chunk_count,
        error=document.error,
        uploaded_by=document.uploaded_by,
    )
