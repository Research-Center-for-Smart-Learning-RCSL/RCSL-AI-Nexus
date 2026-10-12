"""Postgres fences shared by every gateway and knowledge writer.

Begin commits before content changes. Request End joins the content transaction
so neither can become visible first; background publication End commits only
after the vector store has acknowledged its writes. Failed or crashed writers
retain their dirty fence for explicit operator recovery, never a TTL reset.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.sqlalchemy_models.knowledge import (
    KnowledgeCollectionRow,
    KnowledgeTenantEpochRow,
)
from app.domain.exceptions import NoAvailableModelError
from app.domain.ports.grounding_ports import KnowledgeEpoch


class PostgresKnowledgeEpochs:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        tenant_id: str,
        *,
        mutation_session: AsyncSession | None = None,
    ) -> None:
        self._sessions = sessions
        self._tenant = tenant_id
        self._mutation_session = mutation_session

    async def read(self, collection_id: str | None) -> KnowledgeEpoch | None:
        # A fresh physical transaction each time: never an ORM identity-map or
        # repeatable-read snapshot inherited from the chat request.
        async with self._sessions() as session:
            if collection_id is None:
                tenant = await session.get(KnowledgeTenantEpochRow, self._tenant)
                return (
                    KnowledgeEpoch(
                        tenant.epoch,
                        tenant.mutations_in_progress,
                        tenant.embedding_identity if not tenant.index_requires_rebuild else None,
                        tenant.index_requires_rebuild,
                    )
                    if tenant
                    else KnowledgeEpoch(0, 0)
                )
            # One statement snapshot: the tenant's space pin and collection's
            # fence cannot come from opposite sides of a maintenance commit.
            row = (
                await session.execute(
                    select(
                        KnowledgeCollectionRow.epoch,
                        KnowledgeCollectionRow.mutations_in_progress,
                        KnowledgeTenantEpochRow.embedding_identity,
                        KnowledgeTenantEpochRow.index_requires_rebuild,
                    )
                    .select_from(KnowledgeCollectionRow)
                    .outerjoin(
                        KnowledgeTenantEpochRow,
                        KnowledgeTenantEpochRow.tenant_id == KnowledgeCollectionRow.tenant_id,
                    )
                    .where(
                        KnowledgeCollectionRow.id == collection_id,
                        KnowledgeCollectionRow.tenant_id == self._tenant,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            epoch, mutations, identity, requires_rebuild = row
            return KnowledgeEpoch(
                epoch,
                mutations,
                identity if not requires_rebuild else None,
                bool(requires_rebuild),
            )

    @asynccontextmanager
    async def mutation(self, collection_id: str) -> AsyncIterator[None]:
        async with self._sessions() as session:
            # Collection first, then tenant, including End. A request may
            # already hold the collection row while deleting it; taking the
            # tenant first here would deadlock its End against this Begin.
            collection_began = await session.scalar(
                update(KnowledgeCollectionRow)
                .where(
                    KnowledgeCollectionRow.id == collection_id,
                    KnowledgeCollectionRow.tenant_id == self._tenant,
                )
                .values(
                    epoch=KnowledgeCollectionRow.epoch + 1,
                    mutations_in_progress=KnowledgeCollectionRow.mutations_in_progress + 1,
                )
                .returning(KnowledgeCollectionRow.id)
            )
            stmt = insert(KnowledgeTenantEpochRow).values(
                tenant_id=self._tenant, epoch=1, mutations_in_progress=1
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[KnowledgeTenantEpochRow.tenant_id],
                    set_={
                        "epoch": KnowledgeTenantEpochRow.epoch + 1,
                        "mutations_in_progress": KnowledgeTenantEpochRow.mutations_in_progress + 1,
                    },
                )
            )
            await session.commit()
        # No finally: failure/unknown outcome must remain fenced. A rollback
        # of a request's End also leaves its separately committed Begin dirty.
        yield
        if self._mutation_session is not None:
            await self._end(self._mutation_session, collection_id, collection_began is not None)
        else:
            async with self._sessions() as session:
                await self._end(session, collection_id, collection_began is not None)
                await session.commit()

    async def _end(self, session: AsyncSession, collection_id: str, collection_began: bool) -> None:
        # A new collection is invisible at Begin; its first epoch is published
        # with creation. A deleted collection stays absent (never resurrect it).
        values = {"epoch": KnowledgeCollectionRow.epoch + 1}
        if collection_began:
            values["mutations_in_progress"] = KnowledgeCollectionRow.mutations_in_progress - 1
        await session.execute(
            update(KnowledgeCollectionRow)
            .where(
                KnowledgeCollectionRow.id == collection_id,
                KnowledgeCollectionRow.tenant_id == self._tenant,
            )
            .values(**values)
        )
        await session.execute(
            update(KnowledgeTenantEpochRow)
            .where(
                KnowledgeTenantEpochRow.tenant_id == self._tenant,
                KnowledgeTenantEpochRow.mutations_in_progress > 0,
            )
            .values(
                epoch=KnowledgeTenantEpochRow.epoch + 1,
                mutations_in_progress=KnowledgeTenantEpochRow.mutations_in_progress - 1,
            )
        )

    async def bind_embedding_identity(self, identity: str) -> None:
        async with self._sessions() as session:
            # Begin has created the row. Conditional publication ensures two
            # indexers with incompatible same-size vectors cannot mix spaces.
            accepted = await session.scalar(
                update(KnowledgeTenantEpochRow)
                .where(
                    KnowledgeTenantEpochRow.tenant_id == self._tenant,
                    KnowledgeTenantEpochRow.index_requires_rebuild.is_(False),
                    (KnowledgeTenantEpochRow.embedding_identity.is_(None))
                    | (KnowledgeTenantEpochRow.embedding_identity == identity),
                )
                .values(embedding_identity=identity)
                .returning(KnowledgeTenantEpochRow.tenant_id)
            )
            if accepted is None:
                raise NoAvailableModelError(
                    detail="knowledge index space is incompatible or requires a full legacy rebuild"
                )
            await session.commit()
