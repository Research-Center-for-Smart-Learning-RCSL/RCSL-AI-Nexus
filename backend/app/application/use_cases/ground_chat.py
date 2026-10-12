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
from dataclasses import replace

from app.application.use_cases.search_knowledge import DEFAULT_TOP_K, MAX_TOP_K, SearchKnowledge
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import Message
from app.domain.entities.knowledge import RetrievedPassage
from app.domain.ports.grounding_ports import GroundingRecordStorePort, KnowledgeEpochPort
from app.domain.services.grounding_records import (
    GROUNDING_RECORD_TTL,
    MAX_GROUNDING_LOOKBACK,
    MAX_GROUNDING_RECORD_BYTES,
    RETRIEVAL_CONFIG_VERSION,
    GroundingAnchor,
    anchor_hashes,
    decode_chain,
    encode_chain,
    keyed_digest,
    replay,
)
from app.domain.services.prompt_assembly import (
    MAX_PASSAGE_CHARS,
    build_context_message,
    ground,
    query_from,
)

logger = logging.getLogger(__name__)


class GroundChat:
    def __init__(
        self,
        search: SearchKnowledge,
        *,
        records: GroundingRecordStorePort | None = None,
        epochs: KnowledgeEpochPort | None = None,
        server_key: bytes | None = None,
    ) -> None:
        self._search = search
        self._records = records
        self._epochs = epochs
        self._server_key = server_key

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
        if self._records is not None and self._epochs is not None and self._server_key:
            self._search.authorize_grounding(actor)
            try:
                return await self._stable_ground(actor, messages, collection_id, top_k)
            except Exception as exc:
                # Shared-state availability is optional grounding, never a
                # reason to reuse stale content or fail an otherwise valid chat.
                logger.warning("grounding_replay_unavailable reason=%s", type(exc).__name__)
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

    async def _stable_ground(
        self, actor: Actor, messages: list[Message], collection_id: str | None, top_k: int
    ) -> tuple[list[Message], list[RetrievedPassage]]:
        if self._epochs is None or self._records is None or not self._server_key:
            raise RuntimeError("stable grounding requires shared epochs, records and server key")
        before = await self._epochs.read(collection_id)
        if (
            before is None
            or not before.clean
            or before.index_requires_rebuild
            or before.embedding_identity is None
        ):
            return list(messages), []
        top_k = max(1, min(top_k, MAX_TOP_K))
        identity = keyed_digest(
            self._server_key,
            "grounding-record",
            [
                actor.tenant_id,
                actor.api_key_id or actor.id,
                "collection" if collection_id is not None else "tenant",
                collection_id,
                top_k,
                RETRIEVAL_CONFIG_VERSION,
                before.embedding_identity,
                before.epoch,
            ],
        )
        # Look backwards through raw user anchors. A record stores its complete
        # ordered chain, so replay never relies on the lifetime of older keys.
        hashes = anchor_hashes(messages)
        indexes = list(hashes)
        anchors: list[GroundingAnchor] = []
        last_index = indexes[-1]
        keys = {
            f"grounding:{identity}:{hashes[index]}": index
            for index in reversed(indexes[-MAX_GROUNDING_LOOKBACK:])
        }
        latest_key = next(iter(keys))
        stored = await self._records.get_first(list(keys))
        if stored is not None:
            key, raw = stored
            candidate = decode_chain(raw, messages)
            if candidate and key in keys and candidate[-1].index == keys[key]:
                anchors = candidate
        if not anchors and len(indexes) > MAX_GROUNDING_LOOKBACK:
            # Expired/absent older chain: preserve bounded cold-path work and
            # omit grounding rather than shift untracked historical context.
            return list(messages), []

        if not anchors or anchors[-1].index != last_index:
            passages = await self._search.execute_or_empty(
                actor,
                query_from(messages),
                scope=Scope.CHAT_USE,
                collection_id=collection_id,
                top_k=top_k,
                expected_identity=before.embedding_identity,
            )
            if await self._epochs.read(collection_id) != before:
                return list(messages), []
            # Citations are stored beside their canonical rendering and capped
            # too; retaining uncapped source text would defeat the byte limit.
            passages = [replace(p, text=p.text[:MAX_PASSAGE_CHARS]) for p in passages]
            prefix = hashes[last_index]
            nonce = keyed_digest(self._server_key, "grounding-fence", [identity, prefix])[:32]
            context = build_context_message(passages, nonce=nonce)
            # Empty retrieval is also an immutable anchor. If it later succeeds
            # without an epoch change it must not inject bytes into old history.
            proposal = [
                *anchors,
                GroundingAnchor(
                    prefix, last_index, context.content if context else "", tuple(passages)
                ),
            ]
            raw = encode_chain(proposal)
            while passages and len(raw.encode()) > MAX_GROUNDING_RECORD_BYTES:
                passages.pop()
                context = build_context_message(passages, nonce=nonce)
                proposal[-1] = GroundingAnchor(
                    prefix, last_index, context.content if context else "", tuple(passages)
                )
                raw = encode_chain(proposal)
            if len(raw.encode()) <= MAX_GROUNDING_RECORD_BYTES:
                won = await self._records.set_if_absent(latest_key, raw, GROUNDING_RECORD_TTL)
                if won:
                    anchors = proposal
                else:
                    winner = await self._records.get(latest_key)
                    anchors = decode_chain(winner, messages) if winner is not None else []
            # An over-cap contender replays existing history only; it never
            # adds context that cannot be persisted for the following turn.
        if await self._epochs.read(collection_id) != before:
            return list(messages), []
        return replay(messages, anchors)
