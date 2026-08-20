"""Knowledge search routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.application.use_cases.search_knowledge import SearchKnowledge
from app.domain.entities.actor import Actor
from app.infrastructure.di import (
    build_search_knowledge,
)
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RetrievedPassageResponse,
)

from .base import router


@router.post("/knowledge/search")
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    search: Annotated[SearchKnowledge, Depends(build_search_knowledge)],
) -> KnowledgeSearchResponse:
    """POST rather than GET, because the query is document-adjacent text.

    A query is what a researcher is looking for in unpublished work, which is
    close enough to the content itself to keep out of a URL: query strings reach
    access logs and `Referer` headers, and the NTNU proxy is a third party
    (security.md 15.1). The body reaches neither.
    """
    passages = await search.execute(
        actor,
        payload.query,
        collection_id=payload.collection_id,
        top_k=payload.top_k,
    )
    return KnowledgeSearchResponse(passages=[RetrievedPassageResponse.of(p) for p in passages])
