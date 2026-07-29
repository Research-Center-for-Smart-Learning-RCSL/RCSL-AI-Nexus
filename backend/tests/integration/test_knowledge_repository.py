"""The knowledge base's tenant boundary, against a real Postgres.

The unit fakes have no filter, so they cannot prove one exists; only the real
WHERE clause can. These are the reads and writes that would leak a tenant's
unpublished research if the scoping were wrong, which is the highest
sensitivity class in security.md section 9.1.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresKnowledgeRepository,
    PostgresTenantRepository,
)
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.entities.tenant import Tenant

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def _tenant(session, name: str) -> str:
    tenant_id = str(uuid.uuid4())
    await PostgresTenantRepository(session).save(Tenant(id=tenant_id, name=name))
    return tenant_id


def _collection(tenant_id: str, name: str) -> KnowledgeCollection:
    return KnowledgeCollection(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name)


def _document(tenant_id: str, collection_id: str, filename: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        collection_id=collection_id,
        filename=filename,
        media_type="application/pdf",
        size_bytes=100,
        status=DocumentStatus.UPLOADED,
        uploaded_by="someone",
    )


async def test_a_scoped_repository_sees_only_its_own_collections(session) -> None:
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    await PostgresKnowledgeRepository(session, alpha).save_collection(_collection(alpha, "Papers"))
    await PostgresKnowledgeRepository(session, beta).save_collection(_collection(beta, "Notes"))

    names = [c.name for c in await PostgresKnowledgeRepository(session, alpha).list_collections()]
    assert names == ["Papers"]


async def test_the_same_collection_name_is_available_in_two_tenants(session) -> None:
    """Unique per tenant, not globally: a global constraint would leak that
    another tenant had taken the name."""
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    await PostgresKnowledgeRepository(session, alpha).save_collection(_collection(alpha, "Papers"))
    await PostgresKnowledgeRepository(session, beta).save_collection(_collection(beta, "Papers"))

    assert await PostgresKnowledgeRepository(session, beta).get_collection_by_name("Papers")


async def test_another_tenants_collection_is_not_found_by_id(session) -> None:
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    theirs = _collection(beta, "Private")
    await PostgresKnowledgeRepository(session, beta).save_collection(theirs)

    assert await PostgresKnowledgeRepository(session, alpha).get_collection(theirs.id) is None


async def test_another_tenants_document_is_not_readable_or_deletable_by_id(session) -> None:
    """Naming a document by id must not be enough: the delete carries the tenant
    into its WHERE, so a scoped operation cannot touch another tenant's row even
    when it knows the id."""
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    beta_repo = PostgresKnowledgeRepository(session, beta)
    collection = _collection(beta, "Private")
    await beta_repo.save_collection(collection)
    theirs = _document(beta, collection.id, "secret.pdf")
    await beta_repo.save_document(theirs)

    alpha_repo = PostgresKnowledgeRepository(session, alpha)
    assert await alpha_repo.get_document(theirs.id) is None

    await alpha_repo.delete_document(theirs.id)
    assert await beta_repo.get_document(theirs.id) is not None

    await alpha_repo.set_document_status(theirs.id, DocumentStatus.ERROR, error="tampered")
    still_theirs = await beta_repo.get_document(theirs.id)
    assert still_theirs is not None
    assert still_theirs.status is DocumentStatus.UPLOADED


async def test_a_write_is_stamped_with_the_repositorys_tenant_not_the_entitys(session) -> None:
    """The entity claims another tenant and the repository overrides it, which
    is what makes the boundary structural rather than something each use case
    has to set correctly."""
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    alpha_repo = PostgresKnowledgeRepository(session, alpha)
    collection = _collection(alpha, "Papers")
    await alpha_repo.save_collection(collection)

    lying = _document(beta, collection.id, "mine.pdf")
    await alpha_repo.save_document(lying)

    assert await PostgresKnowledgeRepository(session, beta).get_document(lying.id) is None
    stored = await alpha_repo.get_document(lying.id)
    assert stored is not None
    assert stored.tenant_id == alpha


async def test_document_counts_and_paging_are_scoped(session) -> None:
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    alpha_repo = PostgresKnowledgeRepository(session, alpha)
    beta_repo = PostgresKnowledgeRepository(session, beta)

    mine = _collection(alpha, "Papers")
    theirs = _collection(beta, "Papers")
    await alpha_repo.save_collection(mine)
    await beta_repo.save_collection(theirs)
    for i in range(3):
        await alpha_repo.save_document(_document(alpha, mine.id, f"mine-{i}.pdf"))
    for i in range(5):
        await beta_repo.save_document(_document(beta, theirs.id, f"theirs-{i}.pdf"))

    assert await alpha_repo.count_documents() == 3
    assert len(await alpha_repo.list_documents(limit=50, offset=0)) == 3

    listed = await alpha_repo.list_collections()
    assert [(c.name, c.document_count) for c in listed] == [("Papers", 3)]


async def test_reconciliation_moves_transient_documents_across_every_tenant(session) -> None:
    """Deliberately unscoped: it runs at deploy on behalf of no caller, and a
    crash strands rows in every tenant."""
    alpha, beta = await _tenant(session, "alpha"), await _tenant(session, "beta")
    alpha_repo = PostgresKnowledgeRepository(session, alpha)
    beta_repo = PostgresKnowledgeRepository(session, beta)
    mine, theirs = _collection(alpha, "A"), _collection(beta, "B")
    await alpha_repo.save_collection(mine)
    await beta_repo.save_collection(theirs)

    stuck_a = _document(alpha, mine.id, "a.pdf")
    stuck_b = _document(beta, theirs.id, "b.pdf")
    await alpha_repo.save_document(stuck_a)
    await beta_repo.save_document(stuck_b)
    await alpha_repo.set_document_status(stuck_a.id, DocumentStatus.EXTRACTING)
    await beta_repo.set_document_status(stuck_b.id, DocumentStatus.INDEXING)

    moved = await PostgresKnowledgeRepository.unscoped(session).reconcile_transient_documents(
        "Interrupted by a restart."
    )

    assert moved == 2
    for repo, doc in ((alpha_repo, stuck_a), (beta_repo, stuck_b)):
        reconciled = await repo.get_document(doc.id)
        assert reconciled is not None
        assert reconciled.status is DocumentStatus.ERROR
