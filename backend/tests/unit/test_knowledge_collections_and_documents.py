from __future__ import annotations

import pytest

from app.domain.entities.knowledge import (
    DocumentStatus,
)
from app.domain.exceptions import (
    CollectionNotFoundError,
    CollectionStateConflictError,
    DocumentStateConflictError,
    NotAuthorizedError,
    UploadRejectedError,
)
from tests.unit.manage_knowledge_fixtures import (
    ADMIN,
    PDF,
    PLAIN_USER,
    build,
    document,
)

pytest_plugins = ("tests.unit.manage_knowledge_fixtures",)


async def test_a_plain_user_cannot_read_or_write_the_knowledge_base() -> None:
    """Section 5.2 grants a `user` the chat, their own keys and their own usage. The
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


async def test_the_job_progress_check_refuses_the_same_user() -> None:
    """`assert_may_read` is the ingestion job endpoint's whole authorization,
    and it is a check with no data behind it — the shape most likely to be
    mistaken for dead code and deleted. It was in fact a discarded
    `list_collections` call until 2026-08-02, which is exactly that risk."""
    use_case, *_ = build()

    use_case.assert_may_read(ADMIN)
    with pytest.raises(NotAuthorizedError):
        use_case.assert_may_read(PLAIN_USER)


async def test_a_duplicate_collection_name_is_a_conflict_not_a_constraint_violation() -> None:
    use_case, *_ = build()
    with pytest.raises(CollectionStateConflictError):
        await use_case.create_collection(ADMIN, name="Papers")


async def test_deleting_a_collection_removes_its_documents_bytes_and_rows() -> None:
    """The database cannot clean up the volume, so a row-only delete would leave
    files nothing ever looks at again."""
    doc = document(status=DocumentStatus.INDEXED)
    use_case, knowledge, storage, audit, vectors = build(documents=(doc,))
    storage.originals[doc.id] = PDF

    await use_case.delete_collection(ADMIN, "col-1")

    assert knowledge.collections == {}
    assert knowledge.documents == {}
    assert storage.deleted == [doc.id]
    # The passages go too. Leaving them would make a deleted document keep
    # answering questions, which is the worse of the two failure orders.
    assert vectors.deleted == [doc.id]
    assert ("knowledge.collection_deleted", "col-1", "success") in audit.entries


async def test_a_collection_with_a_document_mid_ingest_cannot_be_deleted() -> None:
    """A background task is going to write to that row after this transaction
    commits, so deleting underneath it leaves the task writing to nothing."""
    use_case, *_ = build(documents=(document(status=DocumentStatus.EXTRACTING),))
    with pytest.raises(DocumentStateConflictError):
        await use_case.delete_collection(ADMIN, "col-1")


async def test_upload_stores_the_bytes_then_records_the_row() -> None:
    use_case, knowledge, storage, audit, vectors = build()

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
    use_case, knowledge, _, _, _ = build(fail_on_put=True)

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
    use_case, _, storage, _, _ = build()
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
    use_case, knowledge, storage, _, _ = build()
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
