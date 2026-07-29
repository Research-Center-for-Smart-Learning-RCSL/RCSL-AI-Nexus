"""Reading and writing a document's ingestion state outside the request.

The same problem `ModelStateCommitter` solves, for the same reason. Ingestion
runs as a background task after the response has gone, so the request's session
is closed; and a terminal `ERROR` written while an exception is propagating
would be rolled back with it if it shared a transaction with the work that
failed.

It is tenant-scoped at construction, like the repositories: the task is started
by a request whose actor's tenant is known, and carrying that through means the
background write cannot land on another tenant's row even if a document id were
wrong.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import KnowledgeDocumentRow
from app.domain.entities.knowledge import DocumentStatus, KnowledgeDocument

logger = logging.getLogger(__name__)


class DocumentStateCommitter:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], tenant_id: str) -> None:
        self._sessions = sessions
        self._tenant_id = tenant_id

    async def get(self, document_id: str) -> KnowledgeDocument | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.id == document_id,
                    KnowledgeDocumentRow.tenant_id == self._tenant_id,
                )
            )
            return m.document_to_domain(row) if row else None

    async def commit(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status.value, "error": error}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        try:
            async with self._sessions() as session:
                await session.execute(
                    update(KnowledgeDocumentRow)
                    .where(
                        KnowledgeDocumentRow.id == document_id,
                        KnowledgeDocumentRow.tenant_id == self._tenant_id,
                    )
                    .values(**values)
                )
                await session.commit()
        except Exception:
            # Nowhere to report: the caller is either already raising or has
            # already returned. Logging is the floor and the deploy-time
            # reconciliation is the backstop, exactly as for model state.
            logger.exception(
                "document_state_commit_failed document=%s status=%s", document_id, status.value
            )
