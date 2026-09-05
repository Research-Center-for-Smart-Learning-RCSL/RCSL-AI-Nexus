"""Context compaction tiers, cheapest first.

Compaction reduces a prompt that would exceed the context ceiling, in place of
refusing it. It is applied only when the API key has compaction enabled, and
only after the exact or estimated count says the prompt is too large.

Four tiers, and a request stops at the first that brings it under the ceiling:

  0 — tool definitions: deduplicate and trim descriptions. Zero inference cost.
  1 — old tool results: replace with a length marker, oldest first. Zero
      inference cost.
  2 — summarise the oldest turns on ``assist``/``qwen7b``. Inference cost,
      serialised, cached. (Not implemented here; see ``compaction_tier2.py``.)

Every tier is lossy and every tier discloses what it did, both in the response
and on the usage record. Silent compaction is the failure this platform was
built to make visible; reintroducing it as a feature is not acceptable. See
``docs/plans/automatic-context-compaction.md`` §3.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.entities.model import Model

logger = logging.getLogger("app.application.use_cases.route_chat_request")

TOOL_DESCRIPTION_CAP = 200
RECENT_MESSAGE_WINDOW = 10


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """What compaction did and what it produced."""

    tier: int
    messages: Sequence[Message]
    tools: Sequence[ToolDefinition]
    tokens_before: int
    tokens_after: int
    disclosure: str


def _compact_tool_definitions(tools: Sequence[ToolDefinition]) -> tuple[list[ToolDefinition], str]:
    """Tier 0: deduplicate tools by name and trim long descriptions.

    Agent clients resend the full tool list on every turn, and duplicates are
    common when a client registers the same tool under the same name with
    slightly different descriptions across turns. Deduplication keeps only the
    last definition of each name, which is what the model would act on.

    Trimming descriptions to a fixed cap loses detail but never loses the
    function's name or parameter schema, which is what a model needs to produce
    a valid call.
    """
    seen: dict[str, int] = {}
    for i, tool in enumerate(tools):
        seen[tool.name] = i
    unique = [tools[i] for i in sorted(seen.values())]

    trimmed: list[ToolDefinition] = []
    descriptions_cut = 0
    for tool in unique:
        if len(tool.description) > TOOL_DESCRIPTION_CAP:
            trimmed.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description[:TOOL_DESCRIPTION_CAP] + "…",
                    parameters=tool.parameters,
                )
            )
            descriptions_cut += 1
        else:
            trimmed.append(tool)

    removed = len(tools) - len(unique)
    parts = []
    if removed:
        parts.append(f"{removed} duplicate tool definition{'s' * (removed != 1)} removed")
    if descriptions_cut:
        parts.append(
            f"{descriptions_cut} tool description{'s' * (descriptions_cut != 1)} "
            f"trimmed to {TOOL_DESCRIPTION_CAP} characters"
        )
    disclosure = f"Tier 0: {', '.join(parts)}" if parts else ""
    return trimmed, disclosure


def _compact_tool_results(
    messages: Sequence[Message],
) -> tuple[list[Message], str]:
    """Tier 1: replace old tool results with a length marker.

    A tool result from twenty turns ago has usually been acted on and consumed
    by a subsequent assistant reply. Replacing it with a short marker preserves
    the conversation structure — the model can still see that a tool was called
    and answered — while recovering the bulk of its token cost.

    Only results outside the most recent window are touched. The window
    protects the tool results the model is currently reasoning about.
    """
    result = list(messages)
    total = len(result)
    cutoff = max(total - RECENT_MESSAGE_WINDOW, 0)

    replaced = 0
    chars_saved = 0
    for i in range(cutoff):
        msg = result[i]
        if msg.role is not MessageRole.TOOL:
            continue
        original_len = len(msg.content)
        if original_len <= 80:
            continue
        marker = (
            f"[tool result removed — was {original_len} characters"
            f"{' from ' + msg.tool_call_id if msg.tool_call_id else ''}]"
        )
        result[i] = Message(
            role=msg.role,
            content=marker,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )
        replaced += 1
        chars_saved += original_len - len(marker)

    disclosure = (
        f"Tier 1: {replaced} old tool result{'s' * (replaced != 1)} replaced with markers "
        f"(~{chars_saved} characters recovered)"
        if replaced
        else ""
    )
    return result, disclosure


CountFn = Callable[[Model, Sequence[Message], Sequence[ToolDefinition]], Awaitable[int | None]]


async def try_compact(
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    counted: int,
    limit: int,
    count_fn: CountFn,
    target: Model,
) -> CompactionResult | None:
    """Apply compaction tiers until the prompt fits, or return None.

    ``count_fn`` is the same counter the guardrail used — exact if the model's
    vocabulary is available, estimated otherwise. The re-count after each tier
    uses the same basis so the comparison is honest.
    """
    tokens_before = counted
    current_messages = messages
    current_tools = tools
    disclosures: list[str] = []

    # -- Tier 0: tool definitions ----------------------------------------
    compacted_tools, t0_disclosure = _compact_tool_definitions(current_tools)
    if t0_disclosure:
        current_tools = compacted_tools
        recount = await count_fn(target, current_messages, current_tools)
        if recount is not None and recount <= limit:
            logger.info(
                "compaction tier 0 sufficient: %d -> %d (limit %d)",
                tokens_before,
                recount,
                limit,
            )
            return CompactionResult(
                tier=0,
                messages=current_messages,
                tools=current_tools,
                tokens_before=tokens_before,
                tokens_after=recount,
                disclosure=t0_disclosure,
            )
        disclosures.append(t0_disclosure)
        if recount is not None:
            counted = recount

    # -- Tier 1: old tool results ----------------------------------------
    compacted_messages, t1_disclosure = _compact_tool_results(current_messages)
    if t1_disclosure:
        current_messages = compacted_messages
        recount = await count_fn(target, current_messages, current_tools)
        if recount is not None and recount <= limit:
            disclosures.append(t1_disclosure)
            logger.info(
                "compaction tier 1 sufficient: %d -> %d (limit %d)",
                tokens_before,
                recount,
                limit,
            )
            return CompactionResult(
                tier=1,
                messages=current_messages,
                tools=current_tools,
                tokens_before=tokens_before,
                tokens_after=recount,
                disclosure="; ".join(disclosures),
            )
        disclosures.append(t1_disclosure)

    # Tiers 0 and 1 were not enough. Return None so the caller can try
    # Tier 2 (summarisation) or refuse.
    return None
