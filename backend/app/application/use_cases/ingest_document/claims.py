"""Ingestion claiming, status, and failure finalization."""

from __future__ import annotations

import logging

from app.application.use_cases.embed_texts import TextEmbedderPort
from app.domain.entities.knowledge import DocumentStatus, KnowledgeDocument
from app.domain.exceptions import DocumentNotFoundError, DocumentStateConflictError
from app.domain.ports.infrastructure_ports import JobProgressPort, JobStatus
from app.domain.ports.knowledge_ports import (
    DocumentParserPort,
    DocumentStoragePort,
    VectorStorePort,
)
from app.domain.ports.repositories import KnowledgeRepositoryPort

from .state import (
    INGESTABLE_STATES,
    JOB_TTL_SECONDS,
    REINDEXABLE_STATES,
    DocumentStateCommitterPort,
)

logger = logging.getLogger("app.application.use_cases.ingest_document")


class IngestionClaimsMixin:
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

        **The claim is a conditional UPDATE, and unlike `claim`'s it has to be.**
        `claim` runs against a row this same request inserted moments ago, so no
        second caller can exist; a re-index is requested against a document that
        has been there for days, and two operators — or two browser tabs — can
        ask at once. Checking the status and then writing it would let both
        through under READ COMMITTED, and both would then delete and re-upsert
        the same Qdrant points, leaving a window where the document is
        unsearchable. The status check below is kept as well as the claim, so the
        common refusal names the state the caller is in rather than reporting a
        lost race.
        """
        if document.status not in REINDEXABLE_STATES:
            raise DocumentStateConflictError(
                detail=f"document {document.id} is {document.status}; nothing to re-index from"
            )
        if self._knowledge is None:
            raise RuntimeError("claim_reindex needs a request-session repository")
        if not await self._knowledge.claim_document_status(
            document.id, REINDEXABLE_STATES, DocumentStatus.INDEXING
        ):
            # The row moved between the read and this write: another re-index (or
            # a delete) got there first. Reported as the conflict it is rather
            # than proceeding to schedule a second task over the same passages.
            raise DocumentStateConflictError(
                detail=f"document {document.id} is already being re-indexed"
            )
        status = JobStatus(
            job_id=job_id, state="queued", target=document.id, message="Queued for re-indexing"
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

    async def _fail(self, job_id: str, document_id: str, message: str) -> None:
        await self._jobs.set(
            JobStatus(job_id=job_id, state="failed", target=document_id, message=message),
            ttl_seconds=JOB_TTL_SECONDS,
        )
