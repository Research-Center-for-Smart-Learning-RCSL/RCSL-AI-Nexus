"""Knowledge document management and deletion ordering."""

from __future__ import annotations

import uuid

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeDocument,
)
from app.domain.exceptions import (
    DocumentStateConflictError,
)
from app.domain.services.upload_policy import assert_upload_allowed, sanitise_filename

from .collections import CollectionManagementMixin
from .constants import DEFAULT_DOCUMENT_PAGE, MAX_DOCUMENT_PAGE, PREVIEW_CHARS


class DocumentManagementMixin(CollectionManagementMixin):
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
            AuditAction.KNOWLEDGE_DOCUMENT_UPLOADED,
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
            AuditAction.KNOWLEDGE_DOCUMENT_DELETED,
            target=document_id,
            detail={"filename": document.filename},
        )
