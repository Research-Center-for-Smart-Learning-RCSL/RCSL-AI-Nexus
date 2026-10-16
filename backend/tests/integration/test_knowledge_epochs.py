"""Knowledge fences across physical PostgreSQL sessions, from migrations."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.knowledge_epochs import PostgresKnowledgeEpochs
from app.adapters.persistence.repositories import (
    PostgresKnowledgeRepository,
    PostgresTenantRepository,
)
from app.adapters.persistence.sqlalchemy_models import (
    KnowledgeCollectionRow,
    KnowledgeDocumentRow,
    KnowledgeTenantEpochRow,
)
from app.domain.entities.knowledge import KnowledgeCollection, KnowledgeDocument
from app.domain.entities.tenant import Tenant
from app.domain.exceptions import NoAvailableModelError

SPACE = '["ollama","embed:1","sha256:exact-weights"]'


@pytest.fixture
async def epochs_context(database_url):
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    tenant, collection = str(uuid.uuid4()), str(uuid.uuid4())
    async with sessions() as session:
        await PostgresTenantRepository(session).save(Tenant(tenant, "epoch-test"))
        await PostgresKnowledgeRepository(session, tenant).save_collection(
            KnowledgeCollection(collection, tenant, "Papers")
        )
        await session.commit()
    yield sessions, tenant, collection
    await engine.dispose()


async def test_begin_and_end_are_shared_clean_epochs(epochs_context):
    sessions, tenant, collection = epochs_context
    writer = PostgresKnowledgeEpochs(sessions, tenant)
    other_gateway = PostgresKnowledgeEpochs(sessions, tenant)
    assert (await other_gateway.read(None)).clean
    async with writer.mutation(collection):
        dirty = await other_gateway.read(None)
        assert dirty.epoch == 1 and dirty.mutations_in_progress == 1
        scoped = await other_gateway.read(collection)
        assert scoped.epoch == 1 and not scoped.clean
        await writer.bind_embedding_identity(SPACE)
    clean = await other_gateway.read(None)
    assert clean.epoch == 2 and clean.clean and clean.embedding_identity == SPACE
    assert (await other_gateway.read(collection)).epoch == 2


async def test_request_end_is_published_atomically_with_document_transaction(epochs_context):
    sessions, tenant, collection = epochs_context
    gateway = PostgresKnowledgeEpochs(sessions, tenant)
    document_id = str(uuid.uuid4())
    async with sessions() as request:
        epochs = PostgresKnowledgeEpochs(sessions, tenant, mutation_session=request)
        async with epochs.mutation(collection):
            await PostgresKnowledgeRepository(request, tenant).save_document(
                KnowledgeDocument(document_id, tenant, collection, "a.txt", "text/plain", 1)
            )
        # End was issued but is not yet visible outside the content transaction.
        assert not (await gateway.read(None)).clean
        async with sessions() as observer:
            assert await observer.get(KnowledgeDocumentRow, document_id) is None
        await request.commit()
    assert (await gateway.read(None)).clean
    async with sessions() as observer:
        assert await observer.get(KnowledgeDocumentRow, document_id) is not None


async def test_rollback_does_not_publish_a_clean_end(epochs_context):
    sessions, tenant, collection = epochs_context
    async with sessions() as request:
        epochs = PostgresKnowledgeEpochs(sessions, tenant, mutation_session=request)
        async with epochs.mutation(collection):
            pass
        await request.rollback()
    gateway = PostgresKnowledgeEpochs(sessions, tenant)
    assert not (await gateway.read(None)).clean
    assert not (await gateway.read(collection)).clean


async def test_concurrent_mutations_do_not_clean_each_others_fences(epochs_context):
    sessions, tenant, collection = epochs_context
    epochs = PostgresKnowledgeEpochs(sessions, tenant)
    first = epochs.mutation(collection)
    second = PostgresKnowledgeEpochs(sessions, tenant).mutation(collection)
    await asyncio.gather(first.__aenter__(), second.__aenter__())
    assert (await epochs.read(None)).mutations_in_progress == 2
    await first.__aexit__(None, None, None)
    assert (await epochs.read(collection)).mutations_in_progress == 1
    await second.__aexit__(None, None, None)
    assert (await epochs.read(None)).epoch == 4
    assert (await epochs.read(collection)).clean


async def test_begin_waiting_on_content_row_does_not_deadlock_request_end(epochs_context):
    sessions, tenant, collection = epochs_context
    async with sessions() as request:
        first = PostgresKnowledgeEpochs(sessions, tenant, mutation_session=request).mutation(
            collection
        )
        await first.__aenter__()
        await request.execute(
            update(KnowledgeCollectionRow)
            .where(KnowledgeCollectionRow.id == collection)
            .values(description="content transaction owns this row")
        )
        second = PostgresKnowledgeEpochs(sessions, tenant).mutation(collection)
        waiting = asyncio.create_task(second.__aenter__())
        # Let the independent Begin reach its row lock; this wait is bounded
        # and the timeout catches the tenant-before-collection lock inversion.
        await asyncio.sleep(0.05)
        assert not waiting.done()
        await asyncio.wait_for(first.__aexit__(None, None, None), timeout=2)
        await request.commit()
        await asyncio.wait_for(waiting, timeout=2)
        await second.__aexit__(None, None, None)
    assert (await PostgresKnowledgeEpochs(sessions, tenant).read(None)).clean


async def test_creation_and_deletion_fence_tenant_without_resurrecting_collection(epochs_context):
    sessions, tenant, _ = epochs_context
    new_id = str(uuid.uuid4())
    gateway = PostgresKnowledgeEpochs(sessions, tenant)
    async with sessions() as request:
        epochs = PostgresKnowledgeEpochs(sessions, tenant, mutation_session=request)
        async with epochs.mutation(new_id):
            await PostgresKnowledgeRepository(request, tenant).save_collection(
                KnowledgeCollection(new_id, tenant, "New")
            )
        assert await gateway.read(new_id) is None
        await request.commit()
    assert (await gateway.read(new_id)).epoch == 1
    async with sessions() as request:
        epochs = PostgresKnowledgeEpochs(sessions, tenant, mutation_session=request)
        async with epochs.mutation(new_id):
            await PostgresKnowledgeRepository(request, tenant).delete_collection(new_id)
        assert not (await gateway.read(None)).clean
        await request.commit()
    assert (await gateway.read(None)).clean
    assert await gateway.read(new_id) is None


async def test_same_dimensions_cannot_change_the_persisted_embedding_space(epochs_context):
    sessions, tenant, collection = epochs_context
    epochs = PostgresKnowledgeEpochs(sessions, tenant)
    async with epochs.mutation(collection):
        await epochs.bind_embedding_identity(SPACE)
        with pytest.raises(NoAvailableModelError):
            await epochs.bind_embedding_identity('["ollama","unrelated:1","other-weights"]')
    assert (await epochs.read(None)).embedding_identity == SPACE


async def test_legacy_upload_pins_future_writes_without_claiming_old_provenance(epochs_context):
    sessions, tenant, collection = epochs_context
    epochs = PostgresKnowledgeEpochs(sessions, tenant)
    async with sessions() as session:
        session.add(KnowledgeTenantEpochRow(tenant_id=tenant, index_requires_rebuild=True))
        await session.commit()
    current = await epochs.read(None)
    assert current.index_requires_rebuild and current.embedding_identity is None
    await epochs.bind_embedding_identity(SPACE)
    current = await epochs.read(collection)
    assert current.embedding_identity == SPACE
    assert current.index_requires_rebuild  # Still legacy: no immutable replay.


async def test_another_tenant_cannot_observe_or_fence_this_collection(epochs_context):
    sessions, tenant, collection = epochs_context
    other = str(uuid.uuid4())
    async with sessions() as session:
        await PostgresTenantRepository(session).save(Tenant(other, "other-tenant"))
        await session.commit()
    theirs = PostgresKnowledgeEpochs(sessions, other)
    ours = PostgresKnowledgeEpochs(sessions, tenant)
    assert await theirs.read(collection) is None
    async with theirs.mutation(collection):
        assert (await ours.read(None)).clean
        assert (await ours.read(collection)).epoch == 0
    assert (await ours.read(collection)).epoch == 0


async def test_migration_marks_existing_documents_as_legacy_without_a_rebuild_in_progress(
    epochs_context, database_url
):
    from alembic import command
    from tests.integration.conftest import _alembic_config

    sessions, tenant, collection = epochs_context
    async with sessions() as session:
        await PostgresKnowledgeRepository(session, tenant).save_document(
            KnowledgeDocument(str(uuid.uuid4()), tenant, collection, "old.txt", "text/plain", 1)
        )
        await session.commit()
    config = _alembic_config(database_url)
    await asyncio.to_thread(command.downgrade, config, "f1b6c8d39a20")
    await asyncio.to_thread(command.upgrade, config, "head")
    current = await PostgresKnowledgeEpochs(sessions, tenant).read(None)
    assert current.index_requires_rebuild and not current.index_rebuilding
    assert current.clean and current.embedding_identity is None


async def test_legacy_tenant_can_publish_new_or_reindexed_document(epochs_context):
    from dataclasses import replace

    from tests.unit.manage_knowledge_fixtures import build_ingest, document
    from tests.unit.test_embedding_and_search import EMBEDDER, POLICY
    from tests.unit.test_grounding_embedding_identity import embedder

    sessions, tenant, collection = epochs_context
    async with sessions() as session:
        session.add(KnowledgeTenantEpochRow(tenant_id=tenant, index_requires_rebuild=True))
        await session.commit()
    doc = replace(document(), tenant_id=tenant, collection_id=collection)
    context = build_ingest(doc)
    context.use_case._embedder, runtime = embedder(
        [replace(EMBEDDER, manifest_digest="exact")], POLICY
    )
    context.use_case._epochs = PostgresKnowledgeEpochs(sessions, tenant)
    assert await context.use_case._index(doc, "new source text", "job") == 1
    assert runtime.calls and context.vectors.points
    current = await context.use_case._epochs.read(None)
    assert current.clean and current.embedding_identity is not None
    assert current.index_requires_rebuild
