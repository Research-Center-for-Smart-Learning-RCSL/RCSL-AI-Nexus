"""Retrieval over the knowledge base.

Two callers, and the difference between them is why this is its own use case
rather than a method on `ManageKnowledge`. An administrator searching from the
management UI is checking what the index contains, and holds `knowledge:read`.
The chat path retrieves on behalf of whoever is asking, and holds
`chat:use`: a `user` who may never list documents but whose question should
still be answered from them.

So the scope is a parameter, chosen by the caller's own entry point, and the
tenant is not: the vector store is constructed with the actor's tenant either
way, so both callers are confined to their own documents without either of them
saying so.

Everything returned is untrusted document text. See `RetrievedPassage`.
"""

from __future__ import annotations

import logging

from app.application.use_cases.embed_texts import TextEmbedderPort
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.knowledge import RetrievedPassage
from app.domain.exceptions import NoAvailableModelError, VectorStoreError
from app.domain.ports.knowledge_ports import VectorStorePort
from app.domain.ports.security_ports import AuthorizationPort

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
"""Bounded because each passage becomes prompt context, and context cost grows
faster than linearly on unified memory. An unbounded `top_k` would be a way to
turn one small question into a large generation."""

MAX_QUERY_CHARS = 2000


class SearchKnowledge:
    def __init__(
        self,
        vectors: VectorStorePort,
        embedder: TextEmbedderPort,
        authz: AuthorizationPort,
    ) -> None:
        self._vectors = vectors
        self._embedder = embedder
        self._authz = authz

    async def execute(
        self,
        actor: Actor,
        query: str,
        *,
        scope: Scope = Scope.KNOWLEDGE_READ,
        collection_id: str | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedPassage]:
        self._authz.require(actor, scope)

        trimmed = query.strip()[:MAX_QUERY_CHARS]
        if not trimmed:
            return []

        vectors = await self._embedder.embed([trimmed])
        if not vectors:
            return []

        return await self._vectors.search(
            vectors[0],
            limit=max(1, min(top_k, MAX_TOP_K)),
            collection_id=collection_id,
        )

    async def execute_or_empty(
        self,
        actor: Actor,
        query: str,
        *,
        scope: Scope = Scope.KNOWLEDGE_READ,
        collection_id: str | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedPassage]:
        """Retrieval that degrades instead of failing.

        For the chat path, where retrieval is an enhancement rather than the
        request: a knowledge base with no embedding policy, or a Qdrant that is
        down, must not turn an ordinary chat into a 503. The authorization
        failure is deliberately *not* caught: that is a decision about who may
        ask, not an availability problem.
        """
        try:
            return await self.execute(
                actor, query, scope=scope, collection_id=collection_id, top_k=top_k
            )
        except (VectorStoreError, NoAvailableModelError) as exc:
            logger.info("retrieval_unavailable actor=%s reason=%s", actor.display, exc.detail)
            return []
