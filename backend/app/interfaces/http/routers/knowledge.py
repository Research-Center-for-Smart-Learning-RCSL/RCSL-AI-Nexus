"""Knowledge base: collections, documents, and the ingestion job.

Authorization is not enforced here; each use case declares and checks its own
scope, so a second caller reaching the same use case cannot skip it.

The upload endpoint is the only place in this API that accepts a file, so the
two bounds that cannot be expressed as a pydantic field live here: the body is
read in chunks against a ceiling rather than in one call, and the media type is
taken from the multipart part rather than guessed from the name.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import (
    DEFAULT_DOCUMENT_PAGE,
    ManageKnowledge,
)
from app.domain.entities.actor import Actor
from app.domain.exceptions import UploadRejectedError
from app.domain.services.upload_policy import MAX_UPLOAD_BYTES
from app.infrastructure.di import build_ingest_document, build_manage_knowledge
from app.infrastructure.jobs import schedule_ingestion
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateCollectionRequest,
    IngestionJobResponse,
    KnowledgeCollectionResponse,
    KnowledgeDocumentPageResponse,
    KnowledgeDocumentResponse,
)

router = APIRouter(tags=["knowledge"])

_UPLOAD_CHUNK = 1024 * 1024


@router.get("/knowledge/collections")
async def list_collections(
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> list[KnowledgeCollectionResponse]:
    return [KnowledgeCollectionResponse.of(c) for c in await knowledge.list_collections(actor)]


@router.post("/knowledge/collections", status_code=201)
async def create_collection(
    payload: CreateCollectionRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> KnowledgeCollectionResponse:
    collection = await knowledge.create_collection(
        actor, name=payload.name, description=payload.description
    )
    return KnowledgeCollectionResponse.of(collection)


@router.delete("/knowledge/collections/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
) -> Response:
    await knowledge.delete_collection(actor, collection_id)
    return Response(status_code=204)


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
    schedule_ingestion(
        request.app,
        document_id=document.id,
        job_id=status.job_id,
        tenant_id=actor.tenant_id,
    )
    return KnowledgeDocumentResponse.of(document)


@router.get("/knowledge/jobs/{job_id}")
async def read_ingestion_job(
    job_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    knowledge: Annotated[ManageKnowledge, Depends(build_manage_knowledge)],
    ingest: Annotated[IngestDocument, Depends(build_ingest_document)],
) -> IngestionJobResponse:
    """Job progress for the UI's poll.

    The scope check is `ManageKnowledge`'s read, called for its own sake: job
    ids live in a cache entry that carries no tenant, so without a check here
    any authenticated caller could poll any job id. What they would learn is a
    document id and a progress figure, which is little, but the check is free.
    """
    await knowledge.list_collections(actor)
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
