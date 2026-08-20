from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_knowledge import ManageKnowledge
from app.domain.entities.knowledge import (
    DocumentChunk,
    DocumentStatus,
)
from app.domain.exceptions import (
    DocumentParseError,
    DocumentStateConflictError,
    NoAvailableModelError,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeEmbedder,
    FakeKnowledge,
    FakeParser,
    FakeVectorStore,
)
from tests.unit.manage_knowledge_fixtures import (
    ADMIN,
    COLLECTION,
    build_ingest,
    document,
)

pytest_plugins = ("tests.unit.manage_knowledge_fixtures",)


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
