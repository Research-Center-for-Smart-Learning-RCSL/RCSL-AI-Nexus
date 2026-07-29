"""Retrieval-augmented chat, without touching the streaming use case.

`RouteChatRequest` is the most carefully ordered file in the tree: the
concurrency slot spans the generator, usage is recorded in `finally`, and
cancellation propagates so a disconnect closes the runtime's request. Adding
retrieval inside it would put a database read and an HTTP call to the embedding
runtime in front of all of that.

So grounding happens *before* it, as a transformation of the messages. This
runs, produces a longer message list, and hands it to `RouteChatRequest`
unchanged. That is the same discipline the metrics work used: the streaming
path gained observation through a wrapped repository rather than a line of
instrumentation inside it.

Retrieval is opt-in per request. It costs an embedding call and consumes
context, and silently grounding every completion would surprise an API caller
who never asked for it.
"""

from __future__ import annotations

import logging

from app.application.use_cases.search_knowledge import DEFAULT_TOP_K, SearchKnowledge
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import Message
from app.domain.entities.knowledge import RetrievedPassage
from app.domain.services.prompt_assembly import ground, query_from

logger = logging.getLogger(__name__)


class GroundChat:
    def __init__(self, search: SearchKnowledge) -> None:
        self._search = search

    async def execute(
        self,
        actor: Actor,
        messages: list[Message],
        *,
        collection_id: str | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> tuple[list[Message], list[RetrievedPassage]]:
        """The grounded conversation and the passages it was grounded on.

        The passages are returned as well as inserted because the caller
        surfaces them as citations: the UI shows which documents an answer drew
        on, which is the difference between a knowledge base an operator can
        audit and one they have to trust.

        Retrieval runs under `chat:use`, not `knowledge:read`. A `user` may
        never list documents and should still have their question answered from
        them; the tenant confinement is the vector store's, not the scope's.

        `execute_or_empty`, so a Qdrant outage or a missing embedding policy
        degrades to an ordinary ungrounded completion rather than failing a
        chat that would otherwise have worked.
        """
        query = query_from(messages)
        if not query:
            return list(messages), []

        passages = await self._search.execute_or_empty(
            actor, query, scope=Scope.CHAT_USE, collection_id=collection_id, top_k=top_k
        )
        if not passages:
            return list(messages), []

        # Counts and document ids only. The passages themselves are document
        # content and are the thing section 9.2 says is never logged by default.
        logger.info(
            "grounded actor=%s passages=%s documents=%s",
            actor.display,
            len(passages),
            len({p.document_id for p in passages}),
        )
        return ground(messages, passages), passages
