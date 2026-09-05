"""Tier 2 context compaction: summarise the oldest turns on ``assist``.

Only reached when tiers 0 and 1 were not enough. Sends the oldest portion
of the conversation to a small, already-resident model (``qwen2.5:7b`` on
the ``assist`` capability), replaces the summarised messages with a single
system message carrying the summary, and returns the shorter conversation.

**Serialised.** At most one summarisation runs at a time, so compaction
can never consume more than one of the four gateway slots. The lock is an
``asyncio.Lock`` held for the duration of the call.

**Cached.** The prefix-hash cache from ``compaction_cache.py`` is checked
before summarising, so a conversation that was already compacted on a
previous turn does not re-summarise. A cache miss is expected on the first
turn that triggers Tier 2; every subsequent turn of the same conversation
hits.

See ``docs/plans/automatic-context-compaction.md`` §5.3 and §5.4.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.entities.model import Model

from .compaction import CompactionResult, CountFn
from .compaction_cache import CompactionCache

logger = logging.getLogger("app.application.use_cases.route_chat_request")

_SUMMARISE_SYSTEM = (
    "Summarise the following conversation history. Preserve every factual claim, "
    "number, decision, file path, code snippet, and action item exactly as stated. "
    "Do not add anything that was not in the original. Do not editorialize. Write "
    "the summary as a flat list of statements, each on its own line, in the order "
    "they appeared. Keep the summary under 500 tokens."
)

_SUMMARY_HEADER = "[Compacted summary of the earliest turns in this conversation]\n\n"

SummariseFn = Callable[[Sequence[Message]], Awaitable[str]]
"""Accept messages, return a summary string.

The orchestrator provides a closure that calls the ``assist`` model through
the same runtime adapter every other request uses. This module never
imports the adapter directly: the model to summarise on is a deployment
decision, and the adapter is an infrastructure choice, neither of which
belongs in the use-case layer.
"""

# How many recent messages to keep untouched. The summary replaces
# everything before this window.
_KEEP_RECENT = 6


async def _do_summarise(
    messages: Sequence[Message],
    n_to_summarise: int,
    summarise_fn: SummariseFn,
) -> Message:
    """Call the summary model and wrap the result as a system message."""
    prefix = list(messages[:n_to_summarise])
    summary_text = await summarise_fn(prefix)
    return Message(
        role=MessageRole.SYSTEM,
        content=_SUMMARY_HEADER + summary_text.strip(),
    )


async def try_tier2(
    *,
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    counted: int,
    limit: int,
    count_fn: CountFn,
    target: Model,
    summarise_fn: SummariseFn,
    cache: CompactionCache | None,
    lock: asyncio.Lock,
) -> CompactionResult | None:
    """Summarise the oldest turns if tiers 0 and 1 were not enough.

    Returns a ``CompactionResult`` if the summary brought the prompt under
    the limit, or ``None`` if not even summarisation was enough (the caller
    should then refuse).
    """
    n_messages = len(messages)
    if n_messages <= _KEEP_RECENT:
        return None

    n_to_summarise = n_messages - _KEEP_RECENT
    tokens_before = counted
    prefix_messages = messages[:n_to_summarise]

    # Check the cache before acquiring the lock. A hit skips the inference
    # call entirely and does not need serialisation.
    if cache is not None:
        cached = await cache.get(prefix_messages, tools, tier=2)
        if cached is not None:
            compacted_messages: Sequence[Message] = (*cached.messages, *messages[n_to_summarise:])
            recount = await count_fn(target, compacted_messages, tools)
            if recount is not None and recount <= limit:
                logger.info(
                    "compaction tier 2 cache hit: %d -> %d (limit %d)",
                    tokens_before,
                    recount,
                    limit,
                )
                return CompactionResult(
                    tier=2,
                    messages=compacted_messages,
                    tools=tools,
                    tokens_before=tokens_before,
                    tokens_after=recount,
                    disclosure=cached.disclosure,
                )

    async with lock:
        # Re-check the cache inside the lock: another request may have
        # populated it while we were waiting.
        if cache is not None:
            cached = await cache.get(prefix_messages, tools, tier=2)
            if cached is not None:
                compacted_messages = (*cached.messages, *messages[n_to_summarise:])
                recount = await count_fn(target, compacted_messages, tools)
                if recount is not None and recount <= limit:
                    logger.info(
                        "compaction tier 2 cache hit (after lock): %d -> %d",
                        tokens_before,
                        recount,
                    )
                    return CompactionResult(
                        tier=2,
                        messages=compacted_messages,
                        tools=tools,
                        tokens_before=tokens_before,
                        tokens_after=recount,
                        disclosure=cached.disclosure,
                    )

        summary_msg = await _do_summarise(messages, n_to_summarise, summarise_fn)
        compacted_messages = (summary_msg, *messages[n_to_summarise:])

        recount = await count_fn(target, compacted_messages, tools)
        disclosure = (
            f"Tier 2: {n_to_summarise} oldest messages summarised into "
            f"{len(summary_msg.content)} characters"
        )

        if recount is not None and recount <= limit:
            logger.info(
                "compaction tier 2 sufficient: %d -> %d (limit %d)",
                tokens_before,
                recount,
                limit,
            )
            result = CompactionResult(
                tier=2,
                messages=compacted_messages,
                tools=tools,
                tokens_before=tokens_before,
                tokens_after=recount,
                disclosure=disclosure,
            )
            if cache is not None:
                from .compaction_cache import CompactionResult as CacheResult

                await cache.put(
                    prefix_messages,
                    tools,
                    tier=2,
                    result=CacheResult(
                        messages=tuple(compacted_messages[:1]),
                        disclosure=disclosure,
                        tier=2,
                        tokens_before=tokens_before,
                        tokens_after=recount,
                    ),
                )
            return result

        logger.warning(
            "compaction tier 2 was not enough: %d -> %s (limit %d)",
            tokens_before,
            recount,
            limit,
        )
        return None


def build_summarise_fn(
    runtime: object,
    ref: str,
    context_length: int | None = None,
) -> SummariseFn:
    """Build a ``SummariseFn`` from a ``ModelRuntimePort``.

    Called once in the composition root or orchestrator, and the resulting
    closure is passed down to ``try_tier2``. Keeps the adapter import out of
    this module.
    """
    from contextlib import aclosing

    from app.domain.ports.model_runtime_port import ModelRuntimePort

    rt: ModelRuntimePort = runtime  # type: ignore[assignment]

    async def _summarise(messages: Sequence[Message]) -> str:
        prompt: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=_SUMMARISE_SYSTEM),
            Message(
                role=MessageRole.USER,
                content="\n\n".join(f"[{m.role.value}] {m.content}" for m in messages if m.content),
            ),
        ]
        parts: list[str] = []
        async with aclosing(
            rt.generate(
                ref,
                prompt,
                max_tokens=600,
                thinking=False,
                context_length=context_length,
            )
        ) as stream:
            async for chunk in stream:
                if chunk.delta:
                    parts.append(chunk.delta)
        return "".join(parts)

    return _summarise
