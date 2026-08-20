"""Ingestion job state and claiming contracts."""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.knowledge import DocumentStatus, KnowledgeDocument

JOB_TTL_SECONDS = 24 * 3600


INGESTABLE_STATES = frozenset({DocumentStatus.UPLOADED, DocumentStatus.ERROR})


REINDEXABLE_STATES = frozenset(
    {DocumentStatus.EXTRACTED, DocumentStatus.INDEXED, DocumentStatus.ERROR}
)


class DocumentStateCommitterPort(Protocol):
    """The narrow seam the detached half needs: read a document, write its
    state, each in its own short transaction. Declared here rather than imported
    from the adapter, so the application layer keeps depending only on ports."""

    async def get(self, document_id: str) -> KnowledgeDocument | None: ...

    async def commit(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None: ...
