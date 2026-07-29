"""Turning an uploaded file into text, as a job rather than a request.

Parsing a large PDF is seconds to minutes and happens in another container, so
it runs detached for the reasons `DownloadModel` gives: the request's session is
closed once the response is sent, and a client should not hold a connection open
waiting for it.

**The document's text never reaches this process's logs.** Failures are recorded
as a class ("pdf: PdfReadError"), never as content, because the content is the
sensitive half of this feature (security.md section 9.2).

Ingestion is two stages. This module owns the first: the bytes go to the
isolated parser and the extracted text is written back to storage, leaving the
document `EXTRACTED`. Indexing into the vector store is the second, and it reads
the stored text rather than parsing again.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.domain.entities.knowledge import DocumentStatus, KnowledgeDocument
from app.domain.exceptions import DocumentNotFoundError, DocumentStateConflictError
from app.domain.ports.infrastructure_ports import JobProgressPort, JobStatus
from app.domain.ports.knowledge_ports import DocumentParserPort, DocumentStoragePort

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 24 * 3600
"""Matches the download job's, and for the same reason: long enough to explain
a finished ingestion the next morning, with the durable outcome in the row."""

INGESTABLE_STATES = frozenset({DocumentStatus.UPLOADED, DocumentStatus.ERROR})
"""A fresh upload, or a retry of one that failed. Not `EXTRACTED` or `INDEXED`:
re-running the parser over a document already read is exposing it to the parser
a second time for no gain."""


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
    ) -> None:
        self._state = state_committer
        self._storage = storage
        self._parser = parser
        self._jobs = jobs

    async def claim(self, document: KnowledgeDocument, job_id: str) -> JobStatus:
        """Move the document into `EXTRACTING` while the caller is still waiting.

        Written here rather than inside the detached task so that a second
        upload-and-ingest of the same document is refused with an answer, the
        same reasoning as `DownloadModel.start`.
        """
        if document.status not in INGESTABLE_STATES:
            raise DocumentStateConflictError(
                detail=f"document {document.id} is {document.status}, not ingestable"
            )
        await self._state.commit(document.id, DocumentStatus.EXTRACTING)
        status = JobStatus(
            job_id=job_id, state="queued", target=document.id, message="Queued for extraction"
        )
        await self._jobs.set(status, ttl_seconds=JOB_TTL_SECONDS)
        return status

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

        await self._storage.put_text(document_id, text)
        await self._state.commit(document_id, DocumentStatus.EXTRACTED)
        await self._jobs.set(
            JobStatus(
                job_id=job_id,
                state="succeeded",
                target=document_id,
                progress=1.0,
                message="Extracted",
            ),
            ttl_seconds=JOB_TTL_SECONDS,
        )

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
