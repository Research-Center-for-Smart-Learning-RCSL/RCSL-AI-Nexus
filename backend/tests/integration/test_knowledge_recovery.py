"""Supported recovery is scoped, audited, conditional, and fails closed on rebuild errors."""

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.adapters.persistence.knowledge_epochs import PostgresKnowledgeEpochs
from app.adapters.persistence.repositories import PostgresKnowledgeRepository
from app.adapters.persistence.sqlalchemy_models import AuditLogRow, KnowledgeTenantEpochRow
from app.domain.entities.actor import Actor, Role
from app.domain.entities.knowledge import KnowledgeDocument
from app.infrastructure.recover_knowledge import rebuild, transition
from tests.integration.test_knowledge_epochs import epochs_context as epochs_context
from tests.unit.test_embedding_and_search import EMBEDDER


def admin(tenant):
    return Actor("admin", "admin", Role.ADMIN, "local", frozenset(), tenant_id=tenant)


async def dirty(sessions, tenant, collection):
    epochs = PostgresKnowledgeEpochs(sessions, tenant)
    with pytest.raises(RuntimeError):
        async with epochs.mutation(collection):
            raise RuntimeError("vector write failed")
    return epochs


async def test_recovery_invalidates_all_chains_and_commits_its_audit_atomically(epochs_context):
    sessions, tenant, collection = epochs_context
    epochs = await dirty(sessions, tenant, collection)
    before = await epochs.read(None)
    value = await transition(
        sessions, admin(tenant), before.epoch, "confirmed vector failure", writers_stopped=True
    )
    after = await epochs.read(None)
    assert after.clean and value == after.epoch > before.epoch
    assert (await epochs.read(collection)).clean
    async with sessions() as session:
        audit = await session.scalar(select(AuditLogRow))
        assert audit.action == "knowledge.recovered" and audit.tenant_id == tenant
        assert audit.detail["previous_dirty"] == 1


@pytest.mark.parametrize("failure", ["stale", "unconfirmed", "wrong-tenant", "not-admin"])
async def test_recovery_refuses_invalid_or_stale_operator_instructions(epochs_context, failure):
    sessions, tenant, collection = epochs_context
    epochs = await dirty(sessions, tenant, collection)
    before = await epochs.read(None)
    actor = admin(tenant)
    if failure == "wrong-tenant":
        actor = replace(actor, tenant_id=str(uuid.uuid4()))
    if failure == "not-admin":
        actor = replace(actor, role=Role.USER)
    with pytest.raises(ValueError):
        await transition(
            sessions,
            actor,
            before.epoch - (failure == "stale"),
            "checked",
            writers_stopped=failure != "unconfirmed",
        )
    assert await epochs.read(None) == before


async def test_audit_failure_rolls_back_recovery(epochs_context):
    sessions, tenant, collection = epochs_context
    epochs = await dirty(sessions, tenant, collection)
    before = await epochs.read(None)

    def reject_audit(session, *args):
        if any(isinstance(row, AuditLogRow) for row in session.new):
            raise RuntimeError("audit unavailable")

    event.listen(Session, "before_flush", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await transition(sessions, admin(tenant), before.epoch, "checked", writers_stopped=True)
    finally:
        event.remove(Session, "before_flush", reject_audit)
    assert await epochs.read(None) == before


@pytest.mark.parametrize("fail", [False, True])
async def test_full_rebuild_verifies_every_document_or_stays_explicitly_rebuilding(
    epochs_context, monkeypatch, fail
):
    sessions, tenant, collection = epochs_context
    async with sessions() as session:
        session.add(KnowledgeTenantEpochRow(tenant_id=tenant, index_requires_rebuild=True))
        for _ in range(2):
            await PostgresKnowledgeRepository(session, tenant).save_document(
                KnowledgeDocument(
                    str(uuid.uuid4()), tenant, collection, "source.txt", "text/plain", 10
                )
            )
        await session.commit()
    storage = SimpleNamespace(read_text=AsyncMock(return_value="source document"))
    vectors = SimpleNamespace(reset_index=AsyncMock(), ensure_ready=AsyncMock(), upsert=AsyncMock())
    target = replace(EMBEDDER, manifest_digest="exact")
    embedder = SimpleNamespace(
        resolve=AsyncMock(return_value=(target, object())),
        embed_with=AsyncMock(return_value=[[0.1, 0.2]]),
    )
    if fail:
        embedder.embed_with.side_effect = RuntimeError("runtime failed")
    monkeypatch.setattr(
        "app.infrastructure.recover_knowledge.FilesystemDocumentStorage", lambda *a: storage
    )
    monkeypatch.setattr(
        "app.infrastructure.recover_knowledge.build_vector_store", lambda *a: vectors
    )
    if fail:
        with pytest.raises(RuntimeError):
            await rebuild(
                sessions, admin(tenant), 0, "full rebuild", writers_stopped=True, embedder=embedder
            )
    else:
        await rebuild(
            sessions, admin(tenant), 0, "full rebuild", writers_stopped=True, embedder=embedder
        )
    epoch = await PostgresKnowledgeEpochs(sessions, tenant).read(None)
    assert epoch.index_rebuilding is fail and epoch.index_requires_rebuild is fail
    vectors.reset_index.assert_awaited_once()
    if fail:
        assert not epoch.clean
        with pytest.raises(ValueError, match="must be resumed"):
            await transition(
                sessions, admin(tenant), epoch.epoch, "unsafe recovery", writers_stopped=True
            )
    else:
        assert epoch.clean and epoch.embedding_identity is not None
        assert vectors.upsert.await_count == 2
        assert all(
            call.kwargs["expected_identity"] == epoch.embedding_identity
            for call in embedder.embed_with.await_args_list
        )
