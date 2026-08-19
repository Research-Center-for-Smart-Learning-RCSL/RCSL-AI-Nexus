"""Knowledge collection management and shared tenant-scoped lookup."""

from __future__ import annotations

import logging
import uuid

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.knowledge import (
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.exceptions import (
    CollectionNotFoundError,
    CollectionStateConflictError,
    DocumentNotFoundError,
    DocumentStateConflictError,
)
from app.domain.ports.knowledge_ports import DocumentStoragePort, VectorStorePort
from app.domain.ports.repositories import KnowledgeRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

from .constants import MAX_DOCUMENT_PAGE

logger = logging.getLogger("app.application.use_cases.manage_knowledge")


class CollectionManagementMixin:
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

    def assert_may_read(self, actor: Actor) -> None:
        """The scope check on its own, for the one caller that needs the check
        without the data.

        Ingestion job progress is keyed by job id in a cache entry that carries
        no tenant, so `IngestDocument.status` cannot make this decision and the
        router must. Until 2026-08-02 it was made by calling `list_collections`
        and discarding the result — correct, but it reads as a stray query, and
        the day someone deletes it as dead code the endpoint quietly becomes
        available to anyone with a session. Authorization stays here rather
        than in the router, per security.md section 5.2.
        """
        self._authz.require(actor, Scope.KNOWLEDGE_READ)

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
            raise CollectionStateConflictError(detail=f"a collection named {name!r} already exists")

        collection = KnowledgeCollection(
            id=str(uuid.uuid4()),
            tenant_id=actor.tenant_id,
            name=name,
            description=description,
        )
        await self._knowledge.save_collection(collection)
        await self._audit.record(
            actor,
            AuditAction.KNOWLEDGE_COLLECTION_CREATED,
            target=collection.id,
            detail={"name": name},
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
            AuditAction.KNOWLEDGE_COLLECTION_DELETED,
            target=collection.id,
            detail={"name": collection.name, "documents": str(len(documents))},
        )

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
