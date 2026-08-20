"""Persistence knowledge boundary."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    KnowledgeCollectionRow,
    KnowledgeDocumentRow,
)
from app.domain.entities.knowledge import (
    TRANSIENT_DOCUMENT_STATES,
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)

from .shared import _TenantScoped


class PostgresKnowledgeRepository(_TenantScoped):
    """Collections and documents.

    Both tables carry `tenant_id` and both are filtered on it directly rather
    than a document being scoped through its collection. The redundancy is the
    point: a document read is correctly scoped without a join, so there is no
    query shape in which forgetting the join silently widens the boundary.
    """

    # --- collections -----------------------------------------------------

    async def get_collection(self, collection_id: str) -> KnowledgeCollection | None:
        stmt = self._scope(
            select(KnowledgeCollectionRow).where(KnowledgeCollectionRow.id == collection_id),
            KnowledgeCollectionRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return m.collection_to_domain(row, await self.count_documents(collection_id=row.id))

    async def get_collection_by_name(self, name: str) -> KnowledgeCollection | None:
        stmt = self._scope(
            select(KnowledgeCollectionRow).where(KnowledgeCollectionRow.name == name),
            KnowledgeCollectionRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.collection_to_domain(row) if row else None

    async def list_collections(self) -> list[KnowledgeCollection]:
        # One grouped count for every collection rather than a query per row:
        # the listing renders a document count beside each name.
        rows_by_collection = await self._session.execute(
            self._scope(
                select(KnowledgeDocumentRow.collection_id, func.count()).group_by(
                    KnowledgeDocumentRow.collection_id
                ),
                KnowledgeDocumentRow.tenant_id,
            )
        )
        counts: dict[str, int] = {
            str(collection_id): int(count) for collection_id, count in rows_by_collection.all()
        }
        stmt = self._scope(
            select(KnowledgeCollectionRow).order_by(KnowledgeCollectionRow.name),
            KnowledgeCollectionRow.tenant_id,
        )
        rows = (await self._session.scalars(stmt)).all()
        return [m.collection_to_domain(r, counts.get(r.id, 0)) for r in rows]

    async def save_collection(self, collection: KnowledgeCollection) -> None:
        row = m.collection_to_row(collection)
        if self._tenant_id is not None:
            # Stamp rather than trust the entity, as every scoped write here does.
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def delete_collection(self, collection_id: str) -> None:
        stmt = self._scope(
            delete(KnowledgeCollectionRow).where(KnowledgeCollectionRow.id == collection_id),
            KnowledgeCollectionRow.tenant_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    # --- documents -------------------------------------------------------

    async def get_document(self, document_id: str) -> KnowledgeDocument | None:
        stmt = self._scope(
            select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id == document_id),
            KnowledgeDocumentRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.document_to_domain(row) if row else None

    async def list_documents(
        self, *, collection_id: str | None = None, limit: int, offset: int
    ) -> list[KnowledgeDocument]:
        stmt = self._scope(select(KnowledgeDocumentRow), KnowledgeDocumentRow.tenant_id)
        if collection_id is not None:
            stmt = stmt.where(KnowledgeDocumentRow.collection_id == collection_id)
        # `id` as a tiebreaker, not decoration. `uploaded_at` alone leaves rows
        # sharing a timestamp in no defined order between queries, and offset
        # paging over an unstable order can skip a row. That is a cosmetic
        # glitch in the UI and a real failure in `ManageKnowledge._all_documents`,
        # which pages through this to delete a collection: a skipped document
        # keeps its foreign key, so the delete then fails on the constraint
        # after other documents' bytes and vectors are already gone.
        stmt = (
            stmt.order_by(KnowledgeDocumentRow.uploaded_at.desc(), KnowledgeDocumentRow.id)
            .limit(limit)
            .offset(offset)
        )
        rows = await self._session.scalars(stmt)
        return [m.document_to_domain(row) for row in rows]

    async def count_documents(self, *, collection_id: str | None = None) -> int:
        stmt = self._scope(
            select(func.count()).select_from(KnowledgeDocumentRow),
            KnowledgeDocumentRow.tenant_id,
        )
        if collection_id is not None:
            stmt = stmt.where(KnowledgeDocumentRow.collection_id == collection_id)
        return int(await self._session.scalar(stmt) or 0)

    async def save_document(self, document: KnowledgeDocument) -> None:
        row = m.document_to_row(document)
        if self._tenant_id is not None:
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def set_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        # `error` is always written, cleared to NULL when not supplied: a
        # document that fails, is retried and succeeds must not keep displaying
        # the reason it failed the first time.
        values: dict[str, Any] = {"status": status.value, "error": error}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        stmt = self._scope(
            update(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.id == document_id)
            .values(**values),
            KnowledgeDocumentRow.tenant_id,
        )
        await self._session.execute(stmt)

    async def claim_document_status(
        self, document_id: str, expected: frozenset[DocumentStatus], claimed: DocumentStatus
    ) -> bool:
        # The status predicate is what makes this a claim rather than a write:
        # the row moves only if it is still where the caller found it, so of two
        # concurrent claimers exactly one sees a matching row and the other's
        # UPDATE matches nothing. `rowcount` is the answer, the same way
        # `advance_totp_counter` and `consume` read theirs.
        stmt = self._scope(
            update(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.id == document_id,
                KnowledgeDocumentRow.status.in_([s.value for s in expected]),
            )
            .values(status=claimed.value, error=None),
            KnowledgeDocumentRow.tenant_id,
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return (result.rowcount or 0) > 0
        await self._session.flush()

    async def delete_document(self, document_id: str) -> None:
        stmt = self._scope(
            delete(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id == document_id),
            KnowledgeDocumentRow.tenant_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def reconcile_transient_documents(self, error: str) -> int:
        """Deliberately unscoped by tenant: this runs at deploy, on behalf of no
        caller, and a crash strands rows in every tenant. It is constructed
        unscoped for that reason (infrastructure/provision.py)."""
        result = await self._session.execute(
            update(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.status.in_([s.value for s in TRANSIENT_DOCUMENT_STATES]))
            .values(status=DocumentStatus.ERROR.value, error=error)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount
