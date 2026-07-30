"""Knowledge base management: collections and the documents in them.

The tenant boundary is not enforced here and that is deliberate. The repository
and the storage adapter are both constructed with the actor's tenant in the di
builder, so every read filters and every write stamps without this module
naming a tenant at all; a check here would be a second place to forget. See
docs/architecture/security.md section 7.3.

What this module does own is the upload contract: what a file may be
(`upload_policy`), that its bytes reach the volume before a row claims they
exist, and that removing a document removes the bytes as well as the row.
"""

from __future__ import annotations

import logging
import uuid

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.exceptions import (
    CollectionNotFoundError,
    DocumentNotFoundError,
    DocumentStateConflictError,
    ModelStateConflictError,
)
from app.domain.ports.knowledge_ports import DocumentStoragePort, VectorStorePort
from app.domain.ports.repositories import KnowledgeRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.domain.services.upload_policy import assert_upload_allowed, sanitise_filename

logger = logging.getLogger(__name__)

DEFAULT_DOCUMENT_PAGE = 50
MAX_DOCUMENT_PAGE = 200
"""Bounded like the audit log's page, and for the same reason: an operator UI
never needs the whole table, and an unbounded limit is a memory lever on a
table that only grows."""

PREVIEW_CHARS = 20_000
"""How much extracted text a preview may return. Enough to see what the parser
made of a document, which is the question a preview answers, and far short of
the 32 MiB an upload may be."""


class ManageKnowledge:
    def __init__(
        self,
        knowledge: KnowledgeRepositoryPort,
        storage: DocumentStoragePort,
        vectors: VectorStorePort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._knowledge = knowledge
        self._storage = storage
        self._vectors = vectors
        self._authz = authz
        self._audit = audit

    # --- collections -----------------------------------------------------

    async def list_collections(self, actor: Actor) -> list[KnowledgeCollection]:
        self._authz.require(actor, Scope.KNOWLEDGE_READ)
        return await self._knowledge.list_collections()

    async def create_collection(
        self, actor: Actor, *, name: str, description: str = ""
    ) -> KnowledgeCollection:
        self._authz.require(actor, Scope.KNOWLEDGE_WRITE)

        # A clean 409 rather than the unique constraint's 500, matching how a
        # taken model alias and a taken node name are already reported. The
        # lookup is tenant-scoped, so this cannot report another tenant's name
        # as taken.
        if await self._knowledge.get_collection_by_name(name) is not None:
            raise ModelStateConflictError(detail=f"a collection named {name!r} already exists")

        collection = KnowledgeCollection(
            id=str(uuid.uuid4()),
            tenant_id=actor.tenant_id,
            name=name,
            description=description,
        )
        await self._knowledge.save_collection(collection)
        await self._audit.record(
            actor, "knowledge.collection_created", target=collection.id, detail={"name": name}
        )
        # Read back, so the caller receives the server-assigned `created_at`
        # rather than the null the unsaved entity carries. The create paths that
        # returned the unsaved entity produced a body the frontend's parse
        # rejected after the row existed; see PROGRESS.md 2026-07-24.
        stored = await self._knowledge.get_collection(collection.id)
        return stored if stored is not None else collection

    async def delete_collection(self, actor: Actor, collection_id: str) -> None:
        """Removes the collection, its documents' rows, and their stored bytes.

        Deleting the row alone would orphan files on the volume, which the
        database cannot clean up and nothing else would ever look at again.
        """
        self._authz.require(actor, Scope.KNOWLEDGE_WRITE)
        collection = await self._require_collection(collection_id)

        # A document mid-ingest is held by a background task that will write to
        # it after this transaction commits, so deleting underneath it would
        # leave the task writing to a row that is gone.
        documents = await self._all_documents(collection_id)
        if any(d.is_transient for d in documents):
            raise DocumentStateConflictError(
                detail=f"collection {collection_id} has documents still being ingested"
            )

        for document in documents:
            await self._forget_document(document)
        await self._knowledge.delete_collection(collection.id)
        await self._audit.record(
            actor,
            "knowledge.collection_deleted",
            target=collection.id,
            detail={"name": collection.name, "documents": str(len(documents))},
        )

    # --- documents -------------------------------------------------------

    async def list_documents(
        self,
        actor: Actor,
        *,
        collection_id: str | None = None,
        limit: int = DEFAULT_DOCUMENT_PAGE,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDocument], int]:
        self._authz.require(actor, Scope.KNOWLEDGE_READ)
        bounded = max(1, min(limit, MAX_DOCUMENT_PAGE))
        documents = await self._knowledge.list_documents(
            collection_id=collection_id, limit=bounded, offset=max(0, offset)
        )
        total = await self._knowledge.count_documents(collection_id=collection_id)
        return documents, total

    async def get_document(self, actor: Actor, document_id: str) -> KnowledgeDocument:
        self._authz.require(actor, Scope.KNOWLEDGE_READ)
        return await self._require_document(document_id)

    async def document_to_reindex(self, actor: Actor, document_id: str) -> KnowledgeDocument:
        """The document, for a caller that is about to re-index it.

        `KNOWLEDGE_WRITE`, and that is the point of the method existing at all.
        Re-indexing moves the row's status and deletes and rewrites every passage
        the document has in the vector store, so it is a write however cheap it
        is; `get_document` is the read the preview and the table use, and
        reaching a write through it would make this the one place in the module
        where the read scope changes something. `IngestDocument.claim_reindex`
        cannot hold the check itself — it has no authorization port, for the same
        reason `claim` does not: the scope is checked by the use case that owns
        the document, exactly as `upload_document` checks before claiming.
        """
        self._authz.require(actor, Scope.KNOWLEDGE_WRITE)
        return await self._require_document(document_id)

    async def read_document_text(
        self, actor: Actor, document_id: str, *, limit: int = PREVIEW_CHARS
    ) -> tuple[str, bool]:
        """The extracted text, bounded, for a preview. Returns it with a flag
        saying whether it was cut.

        **The extracted text, never the original bytes.** A preview that served
        the uploaded file back would hand a browser an attacker-supplied PDF to
        render, which is the plugin surface the isolated parser exists to keep
        out of this deployment; the extracted text has already been through that
        parser and is text. The frontend renders it as text and not as markdown
        for the same reason a retrieved passage is data rather than instructions.

        Bounded because a document is up to 32 MiB of source and nobody reads
        that in a dialog, and an unbounded read is a memory lever on a path any
        reader can reach.
        """
        self._authz.require(actor, Scope.KNOWLEDGE_READ)
        document = await self._require_document(document_id)
        if document.status is DocumentStatus.UPLOADED or document.is_transient:
            # Nothing has been written yet, so the storage read would raise
            # "no stored object" — true but unhelpful, and indistinguishable
            # from a document whose text is genuinely missing.
            raise DocumentStateConflictError(
                detail=f"document {document_id} is {document.status}; no text has been extracted"
            )

        text = await self._storage.read_text(document_id)
        bounded = max(1, min(limit, PREVIEW_CHARS))
        return text[:bounded], len(text) > bounded

    async def upload_document(
        self,
        actor: Actor,
        *,
        collection_id: str,
        filename: str,
        media_type: str,
        data: bytes,
    ) -> KnowledgeDocument:
        """Validate, store the bytes, then record the row.

        That order matters: a row written first would claim a document exists
        while the write to the volume could still fail, and the ingestion task
        would then read nothing. The reverse leaves at worst an unreferenced
        directory, which the next upload of the same id (there is none, ids are
        fresh) never collides with and which nothing serves.
        """
        self._authz.require(actor, Scope.KNOWLEDGE_WRITE)
        await self._require_collection(collection_id)

        assert_upload_allowed(media_type=media_type, size_bytes=len(data), data=data)
        safe_name = sanitise_filename(filename)

        document_id = str(uuid.uuid4())
        await self._storage.put_original(document_id, data)

        document = KnowledgeDocument(
            id=document_id,
            tenant_id=actor.tenant_id,
            collection_id=collection_id,
            filename=safe_name,
            media_type=media_type,
            size_bytes=len(data),
            status=DocumentStatus.UPLOADED,
            uploaded_by=actor.id,
        )
        await self._knowledge.save_document(document)
        # The filename and size are metadata; the document's content is not
        # recorded here and must not be. security.md section 9.2.
        await self._audit.record(
            actor,
            "knowledge.document_uploaded",
            target=document_id,
            detail={
                "filename": safe_name,
                "media_type": media_type,
                "bytes": str(len(data)),
                "collection": collection_id,
            },
        )
        stored = await self._knowledge.get_document(document_id)
        return stored if stored is not None else document

    async def delete_document(self, actor: Actor, document_id: str) -> None:
        self._authz.require(actor, Scope.KNOWLEDGE_WRITE)
        document = await self._require_document(document_id)
        if document.is_transient:
            raise DocumentStateConflictError(
                detail=f"document {document_id} is still being ingested"
            )
        await self._forget_document(document)
        await self._audit.record(
            actor,
            "knowledge.document_deleted",
            target=document_id,
            detail={"filename": document.filename},
        )

    # --- internals -------------------------------------------------------

    async def _forget_document(self, document: KnowledgeDocument) -> None:
        """Passages, then bytes, then the row.

        The row goes last so that a failure in either of the first two leaves a
        document the operator can still see and retry. Both are idempotent, so
        the retry succeeds. The reverse order would leave passages retrievable
        from a document nothing lists, which is the worse failure: a deleted
        document would keep answering questions.
        """
        await self._vectors.delete_document(document.id)
        await self._storage.delete(document.id)
        await self._knowledge.delete_document(document.id)

    async def _all_documents(self, collection_id: str) -> list[KnowledgeDocument]:
        """Every document in a collection, paged through rather than read in one
        unbounded query: this is the delete path, and a collection with tens of
        thousands of documents should not load them all at once."""
        found: list[KnowledgeDocument] = []
        offset = 0
        while True:
            page = await self._knowledge.list_documents(
                collection_id=collection_id, limit=MAX_DOCUMENT_PAGE, offset=offset
            )
            if not page:
                return found
            found.extend(page)
            offset += len(page)

    async def _require_collection(self, collection_id: str) -> KnowledgeCollection:
        collection = await self._knowledge.get_collection(collection_id)
        if collection is None:
            # The repository is tenant-scoped, so another tenant's collection is
            # not found here rather than forbidden, which is the answer that
            # reveals least.
            raise CollectionNotFoundError(detail=f"no collection {collection_id}")
        return collection

    async def _require_document(self, document_id: str) -> KnowledgeDocument:
        document = await self._knowledge.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(detail=f"no document {document_id}")
        return document
