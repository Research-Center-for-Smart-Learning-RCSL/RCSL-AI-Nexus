"""Knowledge base entities.

A collection is a named group of documents; a document is one uploaded file
and the text extracted from it. Both are tenant-scoped, unlike models and
nodes: the documents are the team's unpublished research, which is the highest
sensitivity class in security.md section 9.1, and the tenant boundary is the
control that keeps one tenant's from reaching another's.

`filename` is the name the uploader's browser sent. It is a **display label
only** and never reaches a filesystem path or a URL: storage keys are derived
from `id`, which the platform generates. See adapters/storage/filesystem_documents.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DocumentStatus(StrEnum):
    """The ingestion lifecycle.

    `EXTRACTING` and `INDEXING` are transient, held by a background task, and
    a task does not survive a restart. They are reconciled to `ERROR` at
    deploy for the same reason the model states are (infrastructure/provision.py):
    every operation refuses a transient state, so a row a crash stranded there
    is one nothing but hand-edited SQL could move.
    """

    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


TRANSIENT_DOCUMENT_STATES: frozenset[DocumentStatus] = frozenset(
    {DocumentStatus.EXTRACTING, DocumentStatus.INDEXING}
)


@dataclass(frozen=True, slots=True)
class KnowledgeCollection:
    id: str
    tenant_id: str
    name: str
    description: str = ""
    document_count: int = 0
    """Derived at read time rather than stored, so it cannot drift from the
    documents table the way a maintained counter would."""

    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    id: str
    tenant_id: str
    collection_id: str

    filename: str
    """What the uploader called it. Sanitised for display; never a path."""

    media_type: str
    size_bytes: int

    status: DocumentStatus = DocumentStatus.UPLOADED
    chunk_count: int = 0
    error: str | None = None
    """Operator-facing reason a terminal `ERROR` was reached. Carries a parser
    or embedding failure class, never document content: the content is the
    sensitive part and an error string is read by anyone who can list documents."""

    uploaded_by: str = ""
    uploaded_at: datetime | None = None

    @property
    def is_transient(self) -> bool:
        return self.status in TRANSIENT_DOCUMENT_STATES
