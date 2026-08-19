"""Knowledge documents routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, File, Form, Request, Response, UploadFile

from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import (
    DEFAULT_DOCUMENT_PAGE,
    ManageKnowledge,
)
from app.domain.entities.actor import Actor
from app.domain.exceptions import UploadRejectedError
from app.domain.services.upload_policy import MAX_UPLOAD_BYTES
from app.infrastructure.di import (
    SessionDep,
    build_ingest_document,
    build_manage_knowledge,
)
from app.infrastructure.jobs import schedule_ingestion, schedule_reindex
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    DocumentTextResponse,
    IngestionJobResponse,
    KnowledgeDocumentPageResponse,
    KnowledgeDocumentResponse,
)

from .base import _UPLOAD_CHUNK, router


@router.get("/knowledge/documents")
async def list_documents(
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
    collection_id: str | None = None,
    limit: int = DEFAULT_DOCUMENT_PAGE,
    offset: int = 0,
) -> KnowledgeDocumentPageResponse:
    documents, total = await knowledge.list_documents(
        actor, collection_id=collection_id, limit=limit, offset=offset
    )
    return KnowledgeDocumentPageResponse(
        documents=[KnowledgeDocumentResponse.of(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/knowledge/documents/{document_id}")
async def read_document(
    document_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse.of(await knowledge.get_document(actor, document_id))


@router.post("/knowledge/documents", status_code=202)
async def upload_document(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
    ingest: Annotated[IngestDocument, Depends(build_ingest_document)],
    session: SessionDep,
    collection_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> KnowledgeDocumentResponse:
    """202, not 201: the row exists but the document has not been read yet.

    The bytes are read against a ceiling rather than with a single `read()`,
    because `UploadFile` will happily spool a multi-gigabyte body to disk first
    and the limit would then be enforced after the damage. `content-length` is
    not trusted for this: it is a client-supplied header on a streamed body.
    """
    data = await _read_bounded(file)
    document = await knowledge.upload_document(
        actor,
        collection_id=collection_id,
        filename=file.filename or "document",
        media_type=file.content_type or "application/octet-stream",
        data=data,
    )
    # Claim before scheduling, so a failure to claim is answered to the caller
    # rather than disappearing into a background task.
    status = await ingest.claim(document, str(uuid.uuid4()))

    # Commit before scheduling, and this is the load-bearing line rather than a
    # tidy-up. The insert and the claim both live in this request's transaction,
    # which `session_scope` would otherwise commit only at dependency teardown,
    # after this handler returns. The detached task opens a session of its own
    # and its first act is to read the document, so scheduling first is a race
    # it can lose: it would see nothing, fail the job with "The document was
    # removed while queued", and the upload would never be ingested. Committing
    # here makes the row durable before anything else can look for it. The
    # second commit at teardown then finds nothing pending and is a no-op.
    await session.commit()

    schedule_ingestion(
        request.app,
        document_id=document.id,
        job_id=status.job_id,
        tenant_id=actor.tenant_id,
    )
    return KnowledgeDocumentResponse.of(document)


@router.get("/knowledge/documents/{document_id}/text")
async def read_document_text(
    document_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> DocumentTextResponse:
    """The extracted text, bounded, for the preview dialog.

    The *extracted* text and never the uploaded bytes: serving those back would
    hand a browser an attacker-supplied PDF to render, which is precisely what
    the isolated parser exists to keep out of this deployment.
    """
    text, truncated = await knowledge.read_document_text(actor, document_id)
    return DocumentTextResponse(document_id=document_id, text=text, truncated=truncated)


@router.post("/knowledge/documents/{document_id}/reindex", status_code=202)
async def reindex_document(
    document_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
    ingest: Annotated[IngestDocument, Depends(build_ingest_document)],
    session: SessionDep,
) -> IngestionJobResponse:
    """202: re-indexing from the stored text has been accepted, not finished.

    No parser run and no re-upload — that is the whole point of keeping the
    extracted text. Use it after changing the embedding model or the chunk size,
    which are the two settings that make every stored passage stale.
    """
    document = await knowledge.document_to_reindex(actor, document_id)
    status = await ingest.claim_reindex(document, str(uuid.uuid4()))
    # Committed before scheduling, for the reason `upload_document` spells out:
    # the claim lives in this request's transaction and the detached task opens
    # a session of its own, so an uncommitted claim is a race the task loses.
    await session.commit()
    schedule_reindex(
        request.app, document_id=document_id, job_id=status.job_id, tenant_id=actor.tenant_id
    )
    return IngestionJobResponse.of(status)


@router.get("/knowledge/jobs/{job_id}")
async def read_ingestion_job(
    job_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
    ingest: Annotated[IngestDocument, Depends(build_ingest_document)],
) -> IngestionJobResponse:
    """Job progress for the UI's poll.

    Job ids live in a cache entry that carries no tenant, so `status` cannot
    make this decision and the check has to be made here. What an unchecked
    caller would learn is a document id and a progress figure — little, but the
    check costs nothing. The tenant boundary itself is still not enforced on
    this one read; the job id is a uuid4, and the gap is recorded in
    security.md section 7.3 rather than left in a docstring.
    """
    knowledge.assert_may_read(actor)
    return IngestionJobResponse.of(await ingest.status(job_id))


@router.delete("/knowledge/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> Response:
    await knowledge.delete_document(actor, document_id)
    return Response(status_code=204)


async def _read_bounded(file: UploadFile) -> bytes:
    """Read at most one byte more than the limit, then refuse.

    Reading the extra byte is what distinguishes "exactly at the limit" from
    "over it" without reading the rest of the body.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise UploadRejectedError(detail=f"upload exceeds the {MAX_UPLOAD_BYTES} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)
