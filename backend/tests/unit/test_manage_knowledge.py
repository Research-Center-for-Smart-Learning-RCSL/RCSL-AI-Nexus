"""Knowledge base management and the ingestion job.

The cases worth pinning are the ones a passing happy path would hide: that the
bytes reach storage before a row claims they exist, that deleting removes both,
that a document mid-ingest cannot be pulled out from under its task, and that a
parser failure records a class rather than the parser's own message.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import ManageKnowledge
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.exceptions import (
    CollectionNotFoundError,
    DocumentParseError,
    DocumentStateConflictError,
    ModelStateConflictError,
    NotAuthorizedError,
    UploadRejectedError,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeDocumentState,
    FakeDocumentStorage,
    FakeJobs,
    FakeKnowledge,
    FakeParser,
)

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = Actor(
    id="admin-1",
    display="admin",
    role=Role.ADMIN,
    source="tailnet",
    scopes=frozenset(Scope),
    tenant_id=TENANT,
)
PLAIN_USER = Actor(
    id="u2",
    display="user",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
    tenant_id=TENANT,
)

COLLECTION = KnowledgeCollection(id="col-1", tenant_id=TENANT, name="Papers")
PDF = b"%PDF-1.7\nbody"


def build(
    *, collections=(COLLECTION,), documents=(), fail_on_put: bool = False
) -> tuple[ManageKnowledge, FakeKnowledge, FakeDocumentStorage, FakeAudit]:
    knowledge = FakeKnowledge(collections, documents)
    storage = FakeDocumentStorage(fail_on_put=fail_on_put)
    audit = FakeAudit()
    return (
        ManageKnowledge(
            knowledge=knowledge, storage=storage, authz=RoleAuthorization(), audit=audit
        ),
        knowledge,
        storage,
        audit,
    )


def document(**overrides) -> KnowledgeDocument:
    base = {
        "id": "22222222-2222-2222-2222-222222222222",
        "tenant_id": TENANT,
        "collection_id": "col-1",
        "filename": "paper.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(PDF),
        "status": DocumentStatus.UPLOADED,
    }
    return KnowledgeDocument(**{**base, **overrides})


# --- authorization -------------------------------------------------------


async def test_a_plain_user_cannot_read_or_write_the_knowledge_base() -> None:
    """§5.2 grants a `user` the chat, their own keys and their own usage. The
    knowledge base is an administrative surface; retrieval for chat happens
    server-side under the actor's tenant, so a user never needs the scope."""
    use_case, *_ = build()
    with pytest.raises(NotAuthorizedError):
        await use_case.list_collections(PLAIN_USER)
    with pytest.raises(NotAuthorizedError):
        await use_case.create_collection(PLAIN_USER, name="Mine")
    with pytest.raises(NotAuthorizedError):
        await use_case.upload_document(
            PLAIN_USER,
            collection_id="col-1",
            filename="x.pdf",
            media_type="application/pdf",
            data=PDF,
        )


# --- collections ---------------------------------------------------------


async def test_a_duplicate_collection_name_is_a_conflict_not_a_constraint_violation() -> None:
    use_case, *_ = build()
    with pytest.raises(ModelStateConflictError):
        await use_case.create_collection(ADMIN, name="Papers")


async def test_deleting_a_collection_removes_its_documents_bytes_and_rows() -> None:
    """The database cannot clean up the volume, so a row-only delete would leave
    files nothing ever looks at again."""
    doc = document(status=DocumentStatus.EXTRACTED)
    use_case, knowledge, storage, audit = build(documents=(doc,))
    storage.originals[doc.id] = PDF

    await use_case.delete_collection(ADMIN, "col-1")

    assert knowledge.collections == {}
    assert knowledge.documents == {}
    assert storage.deleted == [doc.id]
    assert ("knowledge.collection_deleted", "col-1", "success") in audit.entries


async def test_a_collection_with_a_document_mid_ingest_cannot_be_deleted() -> None:
    """A background task is going to write to that row after this transaction
    commits, so deleting underneath it leaves the task writing to nothing."""
    use_case, *_ = build(documents=(document(status=DocumentStatus.EXTRACTING),))
    with pytest.raises(DocumentStateConflictError):
        await use_case.delete_collection(ADMIN, "col-1")


# --- upload --------------------------------------------------------------


async def test_upload_stores_the_bytes_then_records_the_row() -> None:
    use_case, knowledge, storage, audit = build()

    stored = await use_case.upload_document(
        ADMIN,
        collection_id="col-1",
        filename="../../etc/passwd.pdf",
        media_type="application/pdf",
        data=PDF,
    )

    assert stored.status is DocumentStatus.UPLOADED
    # The filename is sanitised for display and is not what the bytes are
    # stored under: the key comes from the generated id.
    assert stored.filename == "passwd.pdf"
    assert storage.originals[stored.id] == PDF
    assert knowledge.documents[stored.id].filename == "passwd.pdf"
    assert ("knowledge.document_uploaded", stored.id, "success") in audit.entries


async def test_a_failed_write_to_storage_leaves_no_row_claiming_the_document_exists() -> None:
    use_case, knowledge, _, _ = build(fail_on_put=True)

    with pytest.raises(OSError):
        await use_case.upload_document(
            ADMIN,
            collection_id="col-1",
            filename="paper.pdf",
            media_type="application/pdf",
            data=PDF,
        )

    assert knowledge.documents == {}


async def test_upload_into_a_collection_that_does_not_exist_is_refused_before_any_write() -> None:
    use_case, _, storage, _ = build()
    with pytest.raises(CollectionNotFoundError):
        await use_case.upload_document(
            ADMIN,
            collection_id="col-missing",
            filename="paper.pdf",
            media_type="application/pdf",
            data=PDF,
        )
    assert storage.originals == {}


async def test_upload_applies_the_policy_before_touching_storage() -> None:
    use_case, knowledge, storage, _ = build()
    with pytest.raises(UploadRejectedError):
        await use_case.upload_document(
            ADMIN,
            collection_id="col-1",
            filename="thing.exe",
            media_type="application/x-msdownload",
            data=b"MZ",
        )
    assert storage.originals == {}
    assert knowledge.documents == {}


async def test_a_document_mid_ingest_cannot_be_deleted() -> None:
    use_case, *_ = build(documents=(document(status=DocumentStatus.INDEXING),))
    with pytest.raises(DocumentStateConflictError):
        await use_case.delete_document(ADMIN, document().id)


async def test_the_document_page_is_clamped() -> None:
    docs = [document(id=f"3333333{i}-2222-2222-2222-222222222222") for i in range(5)]
    use_case, *_ = build(documents=docs)

    _, total = await use_case.list_documents(ADMIN, limit=10_000)
    assert total == 5

    page, _ = await use_case.list_documents(ADMIN, limit=2)
    assert len(page) == 2


# --- ingestion -----------------------------------------------------------


def build_ingest(
    doc: KnowledgeDocument, *, parser: FakeParser | None = None
) -> tuple[IngestDocument, FakeKnowledge, FakeDocumentStorage, FakeDocumentState, FakeJobs]:
    knowledge = FakeKnowledge((COLLECTION,), (doc,))
    storage = FakeDocumentStorage()
    storage.originals[doc.id] = PDF
    state = FakeDocumentState(knowledge)
    jobs = FakeJobs()
    use_case = IngestDocument(
        state_committer=state,
        storage=storage,
        parser=parser or FakeParser(),
        jobs=jobs,
    )
    return use_case, knowledge, storage, state, jobs


async def test_ingestion_extracts_the_text_and_stores_it_beside_the_original() -> None:
    doc = document()
    use_case, knowledge, storage, state, jobs = build_ingest(doc)

    status = await use_case.claim(doc, "job-1")
    await use_case.run(doc.id, status.job_id)

    assert state.states == ["extracting", "extracted"]
    assert knowledge.documents[doc.id].status is DocumentStatus.EXTRACTED
    # Kept rather than re-derived, so re-indexing never runs the parser again.
    assert storage.texts[doc.id] == "extracted text"
    assert jobs.rows["job-1"].state == "succeeded"


async def test_claim_refuses_a_document_that_is_already_extracted() -> None:
    """Re-running the parser over a document already read exposes it to the
    parser a second time for nothing."""
    doc = document(status=DocumentStatus.EXTRACTED)
    use_case, *_ = build_ingest(doc)
    with pytest.raises(DocumentStateConflictError):
        await use_case.claim(doc, "job-1")


async def test_a_failed_document_may_be_retried() -> None:
    doc = document(status=DocumentStatus.ERROR, error="pdf: PdfReadError")
    use_case, knowledge, *_ = build_ingest(doc)

    await use_case.claim(doc, "job-1")
    await use_case.run(doc.id, "job-1")

    stored = knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.EXTRACTED
    # The previous failure's reason is cleared, not left displayed beside a
    # document that has since succeeded.
    assert stored.error is None


async def test_a_parser_failure_records_a_class_never_the_parsers_message() -> None:
    """A parser message can quote document bytes, and this string is shown to
    anyone who can list documents. security.md 9.2."""
    doc = document()
    parser = FakeParser(raises=DocumentParseError(detail="page 3 says: unpublished result X"))
    use_case, knowledge, _, state, jobs = build_ingest(doc, parser=parser)

    await use_case.claim(doc, "job-1")
    await use_case.run(doc.id, "job-1")

    stored = knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.ERROR
    assert stored.error == "DocumentParseError"
    assert "unpublished result X" not in (stored.error or "")
    assert jobs.rows["job-1"].state == "failed"
    assert "unpublished result X" not in (jobs.rows["job-1"].message or "")


async def test_a_document_removed_while_queued_fails_the_job_rather_than_raising() -> None:
    doc = document()
    use_case, knowledge, _, _, jobs = build_ingest(doc)
    await use_case.claim(doc, "job-1")
    knowledge.documents.clear()

    await use_case.run(doc.id, "job-1")

    assert jobs.rows["job-1"].state == "failed"


async def test_transient_documents_are_reconciled_to_error() -> None:
    """The deploy-time backstop: a task does not survive a restart, and every
    operation refuses a transient state, so a stranded row is otherwise
    unreachable."""
    knowledge = FakeKnowledge(
        (COLLECTION,),
        (
            document(status=DocumentStatus.EXTRACTING),
            document(id="44444444-2222-2222-2222-222222222222", status=DocumentStatus.INDEXED),
        ),
    )
    moved = await knowledge.reconcile_transient_documents("Interrupted by a restart.")

    assert moved == 1
    assert knowledge.documents[document().id].status is DocumentStatus.ERROR
    assert (
        knowledge.documents["44444444-2222-2222-2222-222222222222"].status is DocumentStatus.INDEXED
    )
