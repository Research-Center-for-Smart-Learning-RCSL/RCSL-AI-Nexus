"""Knowledge collections routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Response

from app.application.use_cases.manage_knowledge import (
    ManageKnowledge,
)
from app.domain.entities.actor import Actor
from app.infrastructure.di import (
    build_manage_knowledge,
)
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateCollectionRequest,
    KnowledgeCollectionResponse,
)

from .base import router


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
