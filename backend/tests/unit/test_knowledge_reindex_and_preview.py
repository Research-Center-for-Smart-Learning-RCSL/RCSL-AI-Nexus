from __future__ import annotations

import pytest

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.knowledge import (
    DocumentStatus,
)
from app.domain.exceptions import (
    DocumentStateConflictError,
    NotAuthorizedError,
)
from tests.unit.fakes import (
    FakeParser,
)
from tests.unit.manage_knowledge_fixtures import (
    ADMIN,
    PLAIN_USER,
    TENANT,
    build,
    build_ingest,
    document,
)

pytest_plugins = ("tests.unit.manage_knowledge_fixtures",)


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
