"""Prefix-hash cache for compacted conversation prefixes.

The gateway is stateless: a client replays the entire conversation on every
turn (§4.2). Without a cache, a naive compaction implementation would
re-compact the same history on every turn — an inference call per turn on
Tier 2, or repeated mechanical work on Tiers 0 and 1, either of which
makes compaction worse than no compaction at all on a single-slot runtime.

The property that makes caching viable is that an agent's replayed history
is **stable in its prefix**: turn 15 carries turns 1–14 unchanged. A hash
of the message prefix that was compacted therefore hits on every subsequent
turn until the conversation grows past the next threshold.

Key = SHA-256 of (tier, role+content of each message in the prefix, tool
definitions). Value = the compacted replacement as JSON. TTL = 1 hour.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.entities.chat import Message, ToolDefinition
from app.domain.ports.infrastructure_ports import CachePort

logger = logging.getLogger("app.application.use_cases.route_chat_request")

_TTL = 3600
_PREFIX = "compaction:"


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """What a compaction tier produced."""

    messages: tuple[Message, ...]
    disclosure: str
    tier: int
    tokens_before: int
    tokens_after: int


def _hash_prefix(
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    tier: int,
) -> str:
    h = hashlib.sha256()
    h.update(f"tier={tier}\n".encode())
    for m in messages:
        h.update(f"{m.role}:{m.content}\n".encode())
        if m.tool_calls:
            for tc in m.tool_calls:
                h.update(f"tc:{tc.id}:{tc.name}:{tc.arguments}\n".encode())
        if m.tool_call_id:
            h.update(f"tcid:{m.tool_call_id}\n".encode())
    for t in tools:
        h.update(f"tool:{t.name}:{t.description}\n".encode())
    return _PREFIX + h.hexdigest()


def _result_to_json(result: CompactionResult) -> str:
    return json.dumps(
        {
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    **({"tool_call_id": m.tool_call_id} if m.tool_call_id else {}),
                    **({"name": m.name} if m.name else {}),
                }
                for m in result.messages
            ],
            "disclosure": result.disclosure,
            "tier": result.tier,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
        },
        separators=(",", ":"),
    )


def _result_from_json(raw: str) -> CompactionResult | None:
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    from app.domain.entities.chat import MessageRole

    try:
        msgs = tuple(
            Message(
                role=MessageRole(m["role"]),
                content=m["content"],
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            )
            for m in d["messages"]
        )
        return CompactionResult(
            messages=msgs,
            disclosure=d["disclosure"],
            tier=d["tier"],
            tokens_before=d["tokens_before"],
            tokens_after=d["tokens_after"],
        )
    except (KeyError, ValueError):
        return None


class CompactionCache:
    """Content-addressed cache for compacted conversation prefixes."""

    def __init__(self, cache: CachePort) -> None:
        self._cache = cache

    async def get(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        tier: int,
    ) -> CompactionResult | None:
        key = _hash_prefix(messages, tools, tier)
        raw = await self._cache.get(key)
        if raw is None:
            return None
        result = _result_from_json(raw)
        if result is not None:
            logger.debug("compaction cache hit tier=%d key=%s", tier, key[:24])
        return result

    async def put(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        tier: int,
        result: CompactionResult,
    ) -> None:
        key = _hash_prefix(messages, tools, tier)
        await self._cache.set(key, _result_to_json(result), _TTL)
