"""Persistence knowledge boundary."""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)


class KnowledgeRepositoryPort(Protocol):
    """Collections and documents, tenant-scoped like the rest of the tenant's
    own data. The scoped adapter filters every read and stamps every write, so
    a use case here never names a tenant. See security.md section 7.3."""

    async def get_collection(self, collection_id: str) -> KnowledgeCollection | None: ...
    async def get_collection_by_name(self, name: str) -> KnowledgeCollection | None: ...
    async def list_collections(self) -> list[KnowledgeCollection]: ...
    async def save_collection(self, collection: KnowledgeCollection) -> None: ...

    async def delete_collection(self, collection_id: str) -> None:
        """Only ever called once the collection's documents are gone: the use
        case removes each document's stored bytes first, which the database
        cannot do for it, so a cascade here would orphan files on the volume."""
        ...

    async def get_document(self, document_id: str) -> KnowledgeDocument | None: ...

    async def list_documents(
        self, *, collection_id: str | None = None, limit: int, offset: int
    ) -> list[KnowledgeDocument]: ...

    async def count_documents(self, *, collection_id: str | None = None) -> int: ...

    async def save_document(self, document: KnowledgeDocument) -> None: ...

    async def set_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """A targeted status write, for the same reason `set_status` exists on
        nodes: the ingestion task read the row long before it writes, and a
        full-row save would carry a stale filename or collection back over a
        concurrent edit."""
        ...

    async def claim_document_status(
        self, document_id: str, expected: frozenset[DocumentStatus], claimed: DocumentStatus
    ) -> bool:
        """Take the row only if it is still in one of `expected`. True if taken.

        A conditional UPDATE, not a read followed by a write, and the difference
        is the whole point: two callers checking a status and then writing it
        both pass the check under READ COMMITTED, so both claim. That is the
        same hazard the TOTP counter avoids with `advance_totp_counter`, and it
        reaches the knowledge base through re-indexing, which unlike an upload
        can be requested twice for a document that already exists."""
        ...

    async def delete_document(self, document_id: str) -> None: ...

    async def reconcile_transient_documents(self, error: str) -> int:
        """Move every `extracting` or `indexing` row to `error`, returning the
        count. The ingestion task does not survive a restart, and every
        operation refuses a transient state, so without this a crash mid-ingest
        leaves a row nothing can move. The model registry has the same
        backstop for the same reason."""
        ...
