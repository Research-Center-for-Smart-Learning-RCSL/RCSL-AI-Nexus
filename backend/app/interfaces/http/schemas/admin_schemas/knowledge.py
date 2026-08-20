"""Admin knowledge schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities.knowledge import (
    KnowledgeCollection,
    KnowledgeDocument,
    RetrievedPassage,
)
from app.domain.ports.infrastructure_ports import JobStatus


class KnowledgeCollectionResponse(BaseModel):
    id: str
    name: str
    description: str
    document_count: int
    created_at: datetime | None

    @classmethod
    def of(cls, collection: KnowledgeCollection) -> KnowledgeCollectionResponse:
        return cls(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            document_count=collection.document_count,
            created_at=collection.created_at,
        )


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)


class KnowledgeDocumentResponse(BaseModel):
    id: str
    collection_id: str
    filename: str
    media_type: str
    size_bytes: int
    status: str
    chunk_count: int
    error: str | None
    uploaded_by: str
    uploaded_at: datetime | None

    @classmethod
    def of(cls, document: KnowledgeDocument) -> KnowledgeDocumentResponse:
        return cls(
            id=document.id,
            collection_id=document.collection_id,
            filename=document.filename,
            media_type=document.media_type,
            size_bytes=document.size_bytes,
            status=document.status.value,
            chunk_count=document.chunk_count,
            # The parser's failure class, not its message: a parser message can
            # quote document bytes. See application/use_cases/ingest_document.py.
            error=document.error,
            uploaded_by=document.uploaded_by,
            uploaded_at=document.uploaded_at,
        )


class KnowledgeDocumentPageResponse(BaseModel):
    """Server-paged like the audit log, for the same reason: the table only
    grows, and an unbounded read is a memory lever."""

    documents: list[KnowledgeDocumentResponse]
    total: int
    limit: int
    offset: int


class IngestionJobResponse(BaseModel):
    """Deliberately not `DownloadJobResponse`, whose `model_id` field would name
    a document here. Same shape, honest field names."""

    job_id: str
    document_id: str | None
    """`JobStatus.target` is optional in general; every ingestion job sets it,
    so this is None only for a cache entry written by something else."""

    state: str
    progress: float | None
    message: str | None

    @classmethod
    def of(cls, status: JobStatus) -> IngestionJobResponse:
        return cls(
            job_id=status.job_id,
            document_id=status.target,
            state=status.state,
            progress=status.progress,
            message=status.message,
        )


class DocumentTextResponse(BaseModel):
    """The extracted text of one document, for the preview dialog.

    `truncated` is carried rather than left for the client to infer from the
    length, because the bound is the server's and a client comparing against a
    constant of its own would disagree the first time either changed.
    """

    document_id: str
    text: str
    truncated: bool


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    """Bounded here as well as in the use case: each passage becomes prompt
    context on the chat path, and context cost grows faster than linearly."""


class RetrievedPassageResponse(BaseModel):
    """A passage from a document.

    `text` is **untrusted document content**. Anything rendering it must treat
    it as data: the frontend sanitises markdown with raw HTML disabled
    (frontend.md 7), and prompt assembly marks it as data rather than
    instructions (security.md 7.3).
    """

    document_id: str
    collection_id: str
    index: int
    text: str
    score: float

    @classmethod
    def of(cls, passage: RetrievedPassage) -> RetrievedPassageResponse:
        return cls(
            document_id=passage.document_id,
            collection_id=passage.collection_id,
            index=passage.index,
            text=passage.text,
            score=passage.score,
        )


class KnowledgeSearchResponse(BaseModel):
    passages: list[RetrievedPassageResponse]
