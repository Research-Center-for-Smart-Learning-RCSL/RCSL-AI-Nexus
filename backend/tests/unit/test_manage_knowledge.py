"""Knowledge base management and the ingestion job.

The cases worth pinning are the ones a passing happy path would hide: that the
bytes reach storage before a row claims they exist, that deleting removes both,
that a document mid-ingest cannot be pulled out from under its task, and that a
parser failure records a class rather than the parser's own message.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import ManageKnowledge
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.knowledge import (
    DocumentChunk,
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.exceptions import (
    CollectionNotFoundError,
    CollectionStateConflictError,
    DocumentParseError,
    DocumentStateConflictError,
    NoAvailableModelError,
    NotAuthorizedError,
    UploadRejectedError,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeDocumentState,
    FakeDocumentStorage,
    FakeEmbedder,
    FakeJobs,
    FakeKnowledge,
    FakeParser,
    FakeVectorStore,
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
) -> tuple[ManageKnowledge, FakeKnowledge, FakeDocumentStorage, FakeAudit, FakeVectorStore]:
    knowledge = FakeKnowledge(collections, documents)
    storage = FakeDocumentStorage(fail_on_put=fail_on_put)
    vectors = FakeVectorStore()
    audit = FakeAudit()
    return (
        ManageKnowledge(
            knowledge=knowledge,
            storage=storage,
            vectors=vectors,
            authz=RoleAuthorization(),
            audit=audit,
        ),
        knowledge,
        storage,
        audit,
        vectors,
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


# --- collections ---------------------------------------------------------


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


# --- upload --------------------------------------------------------------


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


# --- ingestion -----------------------------------------------------------


@dataclass
class Ingestion:
    use_case: IngestDocument
    knowledge: FakeKnowledge
    storage: FakeDocumentStorage
    state: FakeDocumentState
    jobs: FakeJobs
    vectors: FakeVectorStore
    embedder: FakeEmbedder


def build_ingest(
    doc: KnowledgeDocument,
    *,
    parser: FakeParser | None = None,
    embedder: FakeEmbedder | None = None,
    vectors: FakeVectorStore | None = None,
) -> Ingestion:
    knowledge = FakeKnowledge((COLLECTION,), (doc,))
    storage = FakeDocumentStorage()
    storage.originals[doc.id] = PDF
    state = FakeDocumentState(knowledge)
    jobs = FakeJobs()
    store = vectors or FakeVectorStore()
    embed = embedder or FakeEmbedder()
    return Ingestion(
        use_case=IngestDocument(
            state_committer=state,
            storage=storage,
            parser=parser or FakeParser(),
            jobs=jobs,
            vectors=store,
            embedder=embed,
            knowledge=knowledge,
        ),
        knowledge=knowledge,
        storage=storage,
        state=state,
        jobs=jobs,
        vectors=store,
        embedder=embed,
    )


async def test_ingestion_extracts_then_indexes_and_stores_the_text_between() -> None:
    doc = document()
    ctx = build_ingest(doc, parser=FakeParser("a paragraph of text"))

    status = await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, status.job_id)

    # EXTRACTED is a durable state between the two stages, not bookkeeping: it
    # is what lets a failed index be retried without re-running the parser.
    #
    # `extracting` is absent from the committer's list on purpose: `claim` runs
    # in the request and writes through the request session, because the row is
    # still uncommitted at that point. Only the detached half writes through the
    # committer. The repository below holds the whole sequence.
    assert ctx.state.states == ["extracted", "indexing", "indexed"]
    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.INDEXED
    assert stored.chunk_count == 1
    assert ctx.storage.texts[doc.id] == "a paragraph of text"
    assert ctx.vectors.points[(doc.id, 0)].text == "a paragraph of text"
    assert ctx.jobs.rows["job-1"].state == "succeeded"


async def test_the_index_is_sized_from_the_resolved_model_and_resolved_once() -> None:
    """The vector size is a property of the routed embedding model, so the index
    cannot be created at startup; and resolving reads three tables, so it must
    not happen once per batch."""
    ctx = build_ingest(document(), parser=FakeParser("text"), embedder=FakeEmbedder(dimensions=768))

    await ctx.use_case.claim(document(), "job-1")
    await ctx.use_case.run(document().id, "job-1")

    assert ctx.vectors.ready_for == [768]
    assert ctx.embedder.resolutions == 1


async def test_reindexing_replaces_a_documents_passages_rather_than_adding_to_them() -> None:
    """Point ids are derived from (document, index), so a re-index that produced
    fewer chunks would leave the tail behind and keep retrieving it forever."""
    doc = document()
    vectors = FakeVectorStore()
    vectors.points[(doc.id, 7)] = DocumentChunk(
        document_id=doc.id, collection_id="col-1", index=7, text="stale", vector=[0.0]
    )
    ctx = build_ingest(doc, parser=FakeParser("fresh text"), vectors=vectors)

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    assert (doc.id, 7) not in ctx.vectors.points
    assert ctx.vectors.points[(doc.id, 0)].text == "fresh text"


async def test_a_document_that_parsed_to_nothing_is_indexed_with_zero_passages() -> None:
    """A scanned PDF with no text layer. Nothing went wrong, and an operator
    reading a zero count learns more than one reading an error."""
    doc = document()
    ctx = build_ingest(doc, parser=FakeParser("   "))

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.INDEXED
    assert stored.chunk_count == 0
    assert ctx.vectors.points == {}


async def test_a_failed_index_leaves_the_extracted_text_in_place_for_a_retry() -> None:
    doc = document()
    ctx = build_ingest(doc, parser=FakeParser("text"), vectors=FakeVectorStore(fail_on_upsert=True))

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.ERROR
    assert stored.error == "VectorStoreError"
    # The parser is the component with the CVE history, and the text it produced
    # survives, so retrying does not put the document through it again.
    assert ctx.storage.texts[doc.id] == "text"
    assert ctx.jobs.rows["job-1"].state == "failed"


async def test_claim_writes_through_the_request_session_not_the_committer() -> None:
    """The row it claims was inserted in the request's uncommitted transaction.

    The committer opens a session of its own, so a claim written through it
    would target a row that connection cannot see yet: zero rows matched, no
    error raised, and the document left at `uploaded` while the parser ran. The
    delete guards read `is_transient`, so they would not fire either. This pins
    that `claim` goes through the repository the insert used.
    """
    doc = document()
    ctx = build_ingest(doc)

    await ctx.use_case.claim(doc, "job-1")

    # Visible through the repository, which is the request session's view.
    assert ctx.knowledge.documents[doc.id].status is DocumentStatus.EXTRACTING
    assert ctx.knowledge.documents[doc.id].is_transient
    # And not written by the detached committer, whose transaction cannot see
    # the row at this point.
    assert ctx.state.states == []


async def test_a_document_being_extracted_cannot_be_deleted_after_a_real_claim() -> None:
    """The end of the chain the bug broke: claim makes the row transient, and
    transient is what stops an operator deleting a document whose background
    task will keep writing passages for it."""
    doc = document()
    ctx = build_ingest(doc)
    await ctx.use_case.claim(doc, "job-1")

    manage = ManageKnowledge(
        knowledge=ctx.knowledge,
        storage=ctx.storage,
        vectors=ctx.vectors,
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )
    with pytest.raises(DocumentStateConflictError):
        await manage.delete_document(ADMIN, doc.id)
    with pytest.raises(DocumentStateConflictError):
        await manage.delete_collection(ADMIN, "col-1")


async def test_a_failure_storing_the_extracted_text_is_a_terminal_state() -> None:
    """`run` promises never to raise and to write every outcome. `put_text` and
    the EXTRACTED commit sat outside every handler, so a full volume or a
    read-only mount left the row transient until the next deploy and the job
    "running" until its TTL."""
    doc = document()
    ctx = build_ingest(doc, parser=FakeParser("text"))

    async def refuse(document_id: str, text: str) -> None:
        raise OSError("no space left on device")

    ctx.storage.put_text = refuse  # type: ignore[method-assign]

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.ERROR
    assert stored.error == "OSError"
    assert not stored.is_transient
    assert ctx.jobs.rows["job-1"].state == "failed"


async def test_a_missing_embedding_policy_fails_the_document_not_the_process() -> None:
    doc = document()
    ctx = build_ingest(
        doc,
        parser=FakeParser("text"),
        embedder=FakeEmbedder(raises=NoAvailableModelError(detail="no policy for embedding")),
    )

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    assert ctx.knowledge.documents[doc.id].status is DocumentStatus.ERROR
    assert ctx.jobs.rows["job-1"].state == "failed"


async def test_claim_refuses_a_document_that_is_already_extracted() -> None:
    """Re-running the parser over a document already read exposes it to the
    parser a second time for nothing."""
    doc = document(status=DocumentStatus.EXTRACTED)
    ctx = build_ingest(doc)
    with pytest.raises(DocumentStateConflictError):
        await ctx.use_case.claim(doc, "job-1")


async def test_a_failed_document_may_be_retried() -> None:
    doc = document(status=DocumentStatus.ERROR, error="pdf: PdfReadError")
    ctx = build_ingest(doc)

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.INDEXED
    # The previous failure's reason is cleared, not left displayed beside a
    # document that has since succeeded.
    assert stored.error is None


async def test_a_parser_failure_records_a_class_never_the_parsers_message() -> None:
    """A parser message can quote document bytes, and this string is shown to
    anyone who can list documents. security.md 9.2."""
    doc = document()
    parser = FakeParser(raises=DocumentParseError(detail="page 3 says: unpublished result X"))
    ctx = build_ingest(doc, parser=parser)

    await ctx.use_case.claim(doc, "job-1")
    await ctx.use_case.run(doc.id, "job-1")

    stored = ctx.knowledge.documents[doc.id]
    assert stored.status is DocumentStatus.ERROR
    assert stored.error == "DocumentParseError"
    assert "unpublished result X" not in (stored.error or "")
    assert ctx.jobs.rows["job-1"].state == "failed"
    assert "unpublished result X" not in (ctx.jobs.rows["job-1"].message or "")


async def test_a_document_removed_while_queued_fails_the_job_rather_than_raising() -> None:
    doc = document()
    ctx = build_ingest(doc)
    await ctx.use_case.claim(doc, "job-1")
    ctx.knowledge.documents.clear()

    await ctx.use_case.run(doc.id, "job-1")

    assert ctx.jobs.rows["job-1"].state == "failed"


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


# --- re-indexing and preview ---------------------------------------------


async def test_reindex_uses_the_stored_text_and_never_the_parser() -> None:
    """The whole point of keeping the extracted text: a changed embedding model
    or chunk size must not send every document through the parser again, because
    the parser is the component with the CVE history."""
    doc = document(status=DocumentStatus.INDEXED, chunk_count=3)
    parser = FakeParser()
    ing = build_ingest(doc, parser=parser)
    ing.storage.texts[doc.id] = "the text that was extracted at upload"

    await ing.use_case.claim_reindex(doc, "job-r1")
    await ing.use_case.run_reindex(doc.id, "job-r1")

    assert ing.knowledge.documents[doc.id].status is DocumentStatus.INDEXED
    assert ing.vectors.points, "passages must have been written"
    assert (await ing.use_case.status("job-r1")).state == "succeeded"
    assert parser.calls == [], "a re-index must never reach the parser"


async def test_reindex_replaces_passages_rather_than_adding_to_them() -> None:
    """A re-index that produced fewer chunks must not leave the tail of the
    previous run retrievable forever."""
    doc = document(status=DocumentStatus.INDEXED)
    ing = build_ingest(doc)
    ing.storage.texts[doc.id] = "short"

    await ing.use_case.claim_reindex(doc, "job-r2")
    await ing.use_case.run_reindex(doc.id, "job-r2")

    assert doc.id in ing.vectors.deleted, "the document's old passages must be dropped first"


async def test_reindex_of_a_document_with_no_stored_text_says_so() -> None:
    """An ERROR document may have failed *during* extraction, in which case
    there is no text and no amount of re-indexing will make one. The operator
    has to be sent to the upload, not back to the button they just pressed."""
    doc = document(status=DocumentStatus.ERROR, error="DocumentParseError")
    ing = build_ingest(doc)  # no text stored

    await ing.use_case.claim_reindex(doc, "job-r3")
    await ing.use_case.run_reindex(doc.id, "job-r3")

    assert ing.knowledge.documents[doc.id].status is DocumentStatus.ERROR
    job = await ing.use_case.status("job-r3")
    assert job.state == "failed"
    assert "upload the document again" in (job.message or "")


async def test_a_freshly_uploaded_document_cannot_be_reindexed() -> None:
    """Nothing has been extracted yet, so this is a full ingest, not a
    re-index. Refused with an answer rather than failing in the task."""
    doc = document(status=DocumentStatus.UPLOADED)
    ing = build_ingest(doc)

    with pytest.raises(DocumentStateConflictError):
        await ing.use_case.claim_reindex(doc, "job-r4")


async def test_a_document_mid_ingest_cannot_be_reindexed() -> None:
    doc = document(status=DocumentStatus.INDEXING)
    ing = build_ingest(doc)

    with pytest.raises(DocumentStateConflictError):
        await ing.use_case.claim_reindex(doc, "job-r5")


async def test_preview_returns_the_extracted_text_bounded() -> None:
    doc = document(status=DocumentStatus.INDEXED)
    use_case, _, storage, *_ = build(documents=(doc,))
    storage.texts[doc.id] = "x" * 100

    text, truncated = await use_case.read_document_text(ADMIN, doc.id, limit=10)

    assert text == "x" * 10
    assert truncated is True


async def test_preview_reports_a_whole_document_as_not_truncated() -> None:
    doc = document(status=DocumentStatus.EXTRACTED)
    use_case, _, storage, *_ = build(documents=(doc,))
    storage.texts[doc.id] = "all of it"

    text, truncated = await use_case.read_document_text(ADMIN, doc.id)

    assert text == "all of it"
    assert truncated is False


async def test_preview_of_a_document_with_nothing_extracted_yet_is_refused() -> None:
    """Reading storage here would raise "no stored object", which is true and
    tells the operator nothing about *why* — and reads identically to a document
    whose text has genuinely gone missing."""
    doc = document(status=DocumentStatus.UPLOADED)
    use_case, *_ = build(documents=(doc,))

    with pytest.raises(DocumentStateConflictError):
        await use_case.read_document_text(ADMIN, doc.id)


async def test_a_plain_user_cannot_preview_a_document() -> None:
    doc = document(status=DocumentStatus.INDEXED)
    use_case, _, storage, *_ = build(documents=(doc,))
    storage.texts[doc.id] = "unpublished research"

    with pytest.raises(NotAuthorizedError):
        await use_case.read_document_text(PLAIN_USER, doc.id)


async def test_the_read_scope_alone_cannot_start_a_reindex() -> None:
    """Re-indexing rewrites every passage the document has and moves its status,
    so it is `knowledge:write`. The route reached it through `get_document`,
    whose check is `knowledge:read`, which made re-indexing the one write in
    this module a reader could perform. Only `admin` holds either scope today,
    so nothing was reachable — but the guard, not the role table, is what the
    module's contract rests on."""
    doc = document(status=DocumentStatus.INDEXED)
    use_case, *_ = build(documents=(doc,))
    reader = Actor(
        id="r1",
        display="reader",
        role=Role.ADMIN,
        source="tailnet",
        scopes=frozenset({Scope.KNOWLEDGE_READ}),
        tenant_id=TENANT,
    )

    # The read it used to travel through still answers, which is what made the
    # gap invisible.
    assert (await use_case.get_document(reader, doc.id)).id == doc.id

    with pytest.raises(NotAuthorizedError):
        await use_case.document_to_reindex(reader, doc.id)


async def test_a_second_concurrent_reindex_is_refused_rather_than_racing() -> None:
    """What `claim_reindex`'s docstring promises, and what a read-then-write
    could not deliver.

    Unlike an upload's claim — which runs against a row the same request just
    inserted, so no second caller exists — a re-index is asked for against a
    document that has been there for days, and two tabs can ask at once. Both
    passing would delete and re-upsert the same Qdrant points, leaving a window
    where the document is unsearchable.
    """
    doc = document(status=DocumentStatus.INDEXED)
    ing = build_ingest(doc)
    ing.storage.texts[doc.id] = "text"

    await ing.use_case.claim_reindex(doc, "job-c1")

    # The second caller still holds the document as it read it, which is exactly
    # the stale value a read-then-write would act on.
    with pytest.raises(DocumentStateConflictError):
        await ing.use_case.claim_reindex(doc, "job-c2")
