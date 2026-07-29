"""Knowledge base ports: where document bytes live, and who reads them.

Both are deliberately narrow. Neither takes a path, a URL, or a filename from
a caller, because the two highest-risk properties of this feature are that an
uploaded file is attacker-controlled bytes and that its name is an
attacker-controlled string.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.entities.knowledge import DocumentChunk, RetrievedPassage


class DocumentStoragePort(Protocol):
    """Where an uploaded document and its extracted text are kept.

    **A caller names a document, never a location.** Every method takes a
    document id the platform generated and the adapter derives the key from it,
    so there is no argument through which a `../` could travel. That is the
    same reasoning as the tenant-scoped repositories: make the dangerous thing
    unreachable rather than validated at each call site.

    Implementations are constructed with a tenant and store under it, so a
    document id belonging to another tenant does not resolve even if one were
    somehow supplied.
    """

    async def put_original(self, document_id: str, data: bytes) -> None: ...

    async def put_text(self, document_id: str, text: str) -> None:
        """The extracted plain text, written beside the original.

        Kept rather than re-derived so that re-indexing (a changed chunk size,
        a new embedding model) does not mean parsing every document again, and
        so the parser runs exactly once per upload: it is the component with
        the CVE history, and each run is an exposure.
        """
        ...

    async def read_original(self, document_id: str) -> bytes: ...

    async def read_text(self, document_id: str) -> str: ...

    async def delete(self, document_id: str) -> None:
        """Remove both objects. Idempotent: deleting a document whose bytes are
        already gone must not fail, or a half-deleted row becomes undeletable."""
        ...


class DocumentParserPort(Protocol):
    """Extracts plain text from an uploaded document.

    The implementation must not parse in this process. PDF and Office parsers
    have a dense CVE history (security.md section 7.3), so parsing happens in a
    separate container that holds no credentials, mounts no volumes, and has no
    route to the database or the internet; this port is the HTTP call to it.
    """

    async def extract_text(self, *, media_type: str, data: bytes) -> str:
        """Raise `DocumentParseError` if the bytes cannot be read as that type.

        The filename is deliberately not a parameter: the parser selects by
        media type, which the upload path has already validated against an
        allowlist, so a crafted extension cannot steer it to a different parser.
        """
        ...


class VectorStorePort(Protocol):
    """The passage index.

    Implementations are constructed with a tenant, like the repositories and the
    document storage, and no method takes one. See
    adapters/vector/qdrant_store.py for how the tenant is enforced twice over,
    and docs/architecture/security.md section 7.3 for why the filter must not be
    something a caller supplies.
    """

    async def ensure_ready(self, vector_size: int) -> None:
        """Create this tenant's index if it is absent, sized for the embedding
        model in use. Called before the first write rather than at startup,
        because the vector size is a property of the routed embedding model and
        is not known until one has been resolved."""
        ...

    async def upsert(self, chunks: Sequence[DocumentChunk]) -> None:
        """Add or replace passages. Ids are derived from the document and the
        passage index, so re-indexing a document overwrites its passages rather
        than accumulating a second copy beside them."""
        ...

    async def delete_document(self, document_id: str) -> None:
        """Remove every passage of one document. Idempotent: a document with no
        passages indexed must still be deletable."""
        ...

    async def search(
        self, vector: Sequence[float], *, limit: int, collection_id: str | None = None
    ) -> list[RetrievedPassage]:
        """Nearest passages within this tenant, optionally within one collection.

        The result is untrusted document text; see `RetrievedPassage`.
        """
        ...
