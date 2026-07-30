"""Turning an uploaded file into text, as a job rather than a request.

Parsing a large PDF is seconds to minutes and happens in another container, so
it runs detached for the reasons `DownloadModel` gives: the request's session is
closed once the response is sent, and a client should not hold a connection open
waiting for it.

**The document's text never reaches this process's logs.** Failures are recorded
as a class ("pdf: PdfReadError"), never as content, because the content is the
sensitive half of this feature (security.md section 9.2).

Ingestion is two stages and this module owns both, with a durable state between
them. The bytes go to the isolated parser and the extracted text is written back
to storage (`EXTRACTED`); then that text is chunked, embedded and indexed
(`INDEXED`). The middle state is not bookkeeping: a failure while indexing
leaves the extracted text in place, so a retry re-indexes from it rather than
sending the document through the parser again. The parser is the component with
the CVE history, and each run of it is an exposure worth not repeating.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.application.use_cases.embed_texts import TextEmbedderPort
from app.domain.entities.knowledge import DocumentChunk, DocumentStatus, KnowledgeDocument
from app.domain.exceptions import DocumentNotFoundError, DocumentStateConflictError
from app.domain.ports.infrastructure_ports import JobProgressPort, JobStatus
from app.domain.ports.knowledge_ports import (
    DocumentParserPort,
    DocumentStoragePort,
    VectorStorePort,
)
from app.domain.ports.repositories import KnowledgeRepositoryPort
from app.domain.services.chunking import chunk_text

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 24 * 3600
"""Matches the download job's, and for the same reason: long enough to explain
a finished ingestion the next morning, with the durable outcome in the row."""

INGESTABLE_STATES = frozenset({DocumentStatus.UPLOADED, DocumentStatus.ERROR})
"""A fresh upload, or a retry of one that failed. Not `EXTRACTED` or `INDEXED`:
re-running the parser over a document already read is exposing it to the parser
a second time for no gain."""

REINDEXABLE_STATES = frozenset(
    {DocumentStatus.EXTRACTED, DocumentStatus.INDEXED, DocumentStatus.ERROR}
)
"""Documents whose text may already be on the volume, so indexing can start from
it and the parser is not run again.

`ERROR` is included and is the interesting one: it covers both a document that
failed *during* extraction (no text stored, and `run_reindex` says so) and one
that failed *after* it, which is the case this whole path exists for. Excluding
it to be safe would refuse exactly the retry that costs nothing."""


class DocumentStateCommitterPort(Protocol):
    """The narrow seam the detached half needs: read a document, write its
    state, each in its own short transaction. Declared here rather than imported
    from the adapter, so the application layer keeps depending only on ports."""

    async def get(self, document_id: str) -> KnowledgeDocument | None: ...

    async def commit(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None: ...


class IngestDocument:
    def __init__(
        self,
        state_committer: DocumentStateCommitterPort,
        storage: DocumentStoragePort,
        parser: DocumentParserPort,
        jobs: JobProgressPort,
        vectors: VectorStorePort,
        embedder: TextEmbedderPort,
        knowledge: KnowledgeRepositoryPort | None = None,
    ) -> None:
        self._state = state_committer
        self._storage = storage
        self._parser = parser
        self._jobs = jobs
        self._vectors = vectors
        self._embedder = embedder
        # The request-session repository, used only by `claim`. `run` is
        # detached and must not touch it, so it is optional and None there,
        # exactly as `DownloadModel` carries `models` for `start` alone.
        self._knowledge = knowledge

    async def claim(self, document: KnowledgeDocument, job_id: str) -> JobStatus:
        """Move the document into `EXTRACTING` while the caller is still waiting.

        Written here rather than inside the detached task so that a second
        upload-and-ingest of the same document is refused with an answer, the
        same reasoning as `DownloadModel.start`.

        **Through the request session, not the state committer**, and the
        distinction is load-bearing rather than stylistic. The document row was
        inserted by `ManageKnowledge.upload_document` moments ago in *this*
        transaction, which has not committed. The committer opens a session of
        its own, so its `UPDATE ... WHERE id = :id` would run on a connection
        that cannot see the row yet, match nothing, and report nothing: the
        document would sit at `uploaded` while the parser ran, `is_transient`
        would stay false so the delete guards would not fire, and the UI would
        stop polling. Writing through the same transaction as the insert is what
        makes the claim real. `DownloadModel.start` does the same thing for the
        same reason; it simply never showed the failure, because the model row
        it claims was committed by an earlier request.
        """
        if document.status not in INGESTABLE_STATES:
            raise DocumentStateConflictError(
                detail=f"document {document.id} is {document.status}, not ingestable"
            )
        if self._knowledge is None:
            raise RuntimeError("claim needs a request-session repository")
        await self._knowledge.set_document_status(document.id, DocumentStatus.EXTRACTING)
        status = JobStatus(
            job_id=job_id, state="queued", target=document.id, message="Queued for extraction"
        )
        await self._jobs.set(status, ttl_seconds=JOB_TTL_SECONDS)
        return status

    async def claim_reindex(self, document: KnowledgeDocument, job_id: str) -> JobStatus:
        """Move the document straight into `INDEXING`, skipping the parser.

        The point of the whole path: the extracted text was kept precisely so a
        changed chunk size or a new embedding model does not mean sending every
        document through the parser again, which is the component with the CVE
        history. `EXTRACTING` is never entered here because nothing extracts.

        Claimed while the caller waits, like `claim`, so a second re-index of
        the same document is refused with an answer rather than racing.
        """
        if document.status not in REINDEXABLE_STATES:
            raise DocumentStateConflictError(
                detail=f"document {document.id} is {document.status}; nothing to re-index from"
            )
        if self._knowledge is None:
            raise RuntimeError("claim_reindex needs a request-session repository")
        await self._knowledge.set_document_status(document.id, DocumentStatus.INDEXING)
        status = JobStatus(
            job_id=job_id, state="queued", target=document.id, message="Queued for re-indexing"
        )
        await self._jobs.set(status, ttl_seconds=JOB_TTL_SECONDS)
        return status

    async def run_reindex(self, document_id: str, job_id: str) -> None:
        """The detached half of a re-index. Never raises, for the same reason
        `run` does not: a background task has nowhere to report.

        `_index` re-commits `INDEXING` and rewrites the job's progress, which is
        redundant with the claim rather than wrong — it keeps one description of
        what indexing does, at the cost of one extra write per re-index.
        """
        document = await self._state.get(document_id)
        if document is None:
            await self._fail(job_id, document_id, "The document was removed while queued.")
            return

        try:
            text = await self._storage.read_text(document_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}"
            logger.warning(
                "reindex_text_missing document=%s job=%s reason=%s", document_id, job_id, reason
            )
            await self._state.commit(document_id, DocumentStatus.ERROR, error=reason)
            # Named precisely, because the remedy differs from every other
            # failure on this path: no amount of retrying re-indexing will
            # produce text that was never extracted, and the operator needs to
            # be sent to the upload rather than to the button they just pressed.
            await self._fail(
                job_id, document_id, "No extracted text is stored; upload the document again."
            )
            return

        try:
            chunk_count = await self._index(document, text, job_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}"
            logger.warning(
                "reindex_failed document=%s job=%s reason=%s", document_id, job_id, reason
            )
            await self._state.commit(document_id, DocumentStatus.ERROR, error=reason)
            await self._fail(job_id, document_id, "Re-indexing failed.")
            return

        await self._state.commit(document_id, DocumentStatus.INDEXED, chunk_count=chunk_count)
        await self._jobs.set(
            JobStatus(
                job_id=job_id,
                state="succeeded",
                target=document_id,
                progress=1.0,
                message=f"Re-indexed {chunk_count} passages",
            ),
            ttl_seconds=JOB_TTL_SECONDS,
        )

    async def status(self, job_id: str) -> JobStatus:
        """Progress for the UI's poll.

        Takes no actor: the caller checks the knowledge read scope before
        reaching this, and adding a second check here would need the job to
        carry a tenant, which the cache entry does not.
        """
        status = await self._jobs.get(job_id)
        if status is None:
            raise DocumentNotFoundError(detail=f"no ingestion job {job_id}")
        return status

    async def run(self, document_id: str, job_id: str) -> None:
        """The detached half. Never raises to its caller.

        Every outcome is written to the job and to the document's state, because
        a background task that raises has nowhere to report. Without the
        terminal write a crashed extraction leaves the row `extracting`, which
        every later operation refuses.
        """
        document = await self._state.get(document_id)
        if document is None:
            await self._fail(job_id, document_id, "The document was removed while queued.")
            return

        try:
            text = await self._extract(document, job_id)
        except Exception as exc:
            # `type(exc).__name__` and the port's own detail, never the parser's
            # body: a parser message can quote the document, and this string is
            # displayed to anyone who can list documents.
            reason = f"{type(exc).__name__}"
            logger.warning(
                "ingestion_failed document=%s job=%s reason=%s", document_id, job_id, reason
            )
            await self._state.commit(document_id, DocumentStatus.ERROR, error=reason)
            await self._fail(job_id, document_id, "Extraction failed.")
            return

        try:
            # Inside the `try`, not before it. These two were outside every
            # handler, so a failure writing the extracted text (a full volume, a
            # read-only mount, a permission error) propagated out of `run` into
            # a caller that only logs: no terminal document state and no
            # terminal job state, leaving the row transient until the next
            # deploy's reconciliation and the job "running" until its TTL. That
            # is precisely what this method's contract says cannot happen.
            await self._storage.put_text(document_id, text)
            await self._state.commit(document_id, DocumentStatus.EXTRACTED)
            chunk_count = await self._index(document, text, job_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}"
            # "post_extraction" rather than "indexing": this block now also
            # covers storing the extracted text, and a log line naming the wrong
            # stage sends an operator to the wrong component.
            logger.warning(
                "post_extraction_failed document=%s job=%s reason=%s", document_id, job_id, reason
            )
            # EXTRACTED is not rolled back on this path. The text is genuinely
            # extracted and stored, so a retry re-indexes from it rather than
            # sending the document through the parser a second time; the status
            # says ERROR because the document is not searchable.
            await self._state.commit(document_id, DocumentStatus.ERROR, error=reason)
            await self._fail(job_id, document_id, "Indexing failed.")
            return
        # Reached only when the text is stored and the passages are in.

        await self._state.commit(document_id, DocumentStatus.INDEXED, chunk_count=chunk_count)
        await self._jobs.set(
            JobStatus(
                job_id=job_id,
                state="succeeded",
                target=document_id,
                progress=1.0,
                message=f"Indexed {chunk_count} passages",
            ),
            ttl_seconds=JOB_TTL_SECONDS,
        )

    async def _index(self, document: KnowledgeDocument, text: str, job_id: str) -> int:
        """Chunk, embed and store. Returns the number of passages indexed.

        The embedding model is resolved once for the whole document rather than
        per batch, because resolving it reads the routing policy, the registry
        and the node table, and none of that changes mid-document.
        """
        await self._state.commit(document.id, DocumentStatus.INDEXING)
        await self._jobs.set(
            JobStatus(
                job_id=job_id,
                state="running",
                target=document.id,
                progress=0.5,
                message="Indexing passages",
            ),
            ttl_seconds=JOB_TTL_SECONDS,
        )

        chunks = chunk_text(text)
        if not chunks:
            # A document that parsed to nothing: a scanned PDF with no text
            # layer is the common case. Indexed with zero passages rather than
            # failed, because nothing went wrong and an operator seeing a zero
            # count learns more than one seeing an error.
            return 0

        target, runtime = await self._embedder.resolve()
        vectors = await self._embedder.embed_with(runtime, [c.text for c in chunks], target.ref)

        # The index is sized for the model that fills it, which is why this
        # happens here rather than at startup: the vector size is a property of
        # the routed model and is not known until one has been resolved.
        await self._vectors.ensure_ready(len(vectors[0]))

        # Replaces this document's passages rather than adding to them: point
        # ids are derived from (document, index), so a re-index of a document
        # that produced fewer chunks would leave the tail behind. Deleting
        # first is what stops a stale passage being retrieved forever.
        await self._vectors.delete_document(document.id)
        await self._vectors.upsert(
            [
                DocumentChunk(
                    document_id=document.id,
                    collection_id=document.collection_id,
                    index=chunk.index,
                    text=chunk.text,
                    vector=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        return len(chunks)

    async def _extract(self, document: KnowledgeDocument, job_id: str) -> str:
        await self._jobs.set(
            JobStatus(
                job_id=job_id,
                state="running",
                target=document.id,
                progress=0.1,
                message="Extracting text",
            ),
            ttl_seconds=JOB_TTL_SECONDS,
        )
        data = await self._storage.read_original(document.id)
        return await self._parser.extract_text(media_type=document.media_type, data=data)

    async def _fail(self, job_id: str, document_id: str, message: str) -> None:
        await self._jobs.set(
            JobStatus(job_id=job_id, state="failed", target=document_id, message=message),
            ttl_seconds=JOB_TTL_SECONDS,
        )
