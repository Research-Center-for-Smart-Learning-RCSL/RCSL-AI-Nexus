"""Extraction, indexing, and reindex orchestration."""

from __future__ import annotations

import logging

from app.domain.entities.knowledge import DocumentChunk, DocumentStatus, KnowledgeDocument
from app.domain.ports.infrastructure_ports import JobStatus
from app.domain.services.chunking import chunk_text

from .claims import IngestionClaimsMixin
from .state import JOB_TTL_SECONDS

logger = logging.getLogger("app.application.use_cases.ingest_document")


class IngestionStagesMixin(IngestionClaimsMixin):
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
