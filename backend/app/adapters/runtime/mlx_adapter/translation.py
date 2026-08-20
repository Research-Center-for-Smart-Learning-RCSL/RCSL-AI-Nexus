"""MLX request/response and tool-call translation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
)

logger = logging.getLogger("app.adapters.runtime.mlx_adapter")

_FINISH_REASONS = {"stop": "stop", "length": "length", "tool_calls": "tool_calls"}


def _finish_reason(reason: str | None, *, called_tools: bool) -> str:
    """`tool_calls` wins, for the reason spelled out in the Ollama adapter: an
    agent loop decides whether to execute a call on this field alone, so a
    generation that produced calls and reports "stop" stalls the conversation.
    A server that already said `tool_calls` agrees, and this changes nothing.

    `called_tools` must mean "calls are being forwarded", not "the server
    mentioned tool calls". The inverse error is the same stall from the other
    end: reporting `tool_calls` with nothing in `tool_calls` leaves the client
    waiting to execute something it was never given, which is worse than the
    "stop" this exists to correct, because there is no content to fall back on.

    **`length` outranks it in turn** (2026-08-09). A generation cut off at the
    token ceiling or the context window may have stopped part way through a
    call's `arguments`, leaving a JSON fragment; reporting `tool_calls` there
    invites the client to execute something incomplete, and reports a truncated
    turn as a finished one on `/v1/responses`, whose `response.incomplete` event
    keys on this value. `stop` is the only reason `tool_calls` needs to
    override, because `stop` is what a *successful* call-producing generation
    reports.
    """
    mapped = _FINISH_REASONS.get(reason or "stop", "stop")
    if called_tools:
        return "length" if mapped == "length" else "tool_calls"
    if mapped == "tool_calls":
        # The server ended on tool calls and none survived parsing. Reporting
        # "stop" at least terminates the turn with whatever content there was.
        logger.warning("mlx reported finish_reason=tool_calls with no usable calls")
        return "stop"
    return mapped


def _message_payload(message: Message) -> dict[str, Any]:
    """The OpenAI message shape, which is what `mlx_lm.server` speaks."""
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                # Arguments stay text here, unlike the Ollama adapter: this is
                # the OpenAI schema, where the field is defined as a string.
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in message.tool_calls
        ]
    if message.role is MessageRole.TOOL and message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    return payload


class _ToolCallAccumulator:
    """Reassembles OpenAI's fragmented tool call deltas into whole calls.

    The OpenAI streaming format splits one call across many frames: the first
    carries `index`, `id` and the function name, and the rest carry successive
    slices of `arguments` under the same index. `CompletionChunk` holds whole
    calls, so the fragments are joined here rather than pushed at the domain —
    which is the same division `sse.py` makes in the other direction.

    Keyed on `index` because that is the only field present on every fragment;
    `id` and `name` appear once, on the first.
    """

    def __init__(self) -> None:
        self._calls: dict[int, dict[str, str]] = {}

    def add(self, raw: Any) -> None:
        if not isinstance(raw, list):
            return
        for entry in raw:
            entry = entry or {}
            index = int(entry.get("index") or 0)
            slot = self._calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if entry.get("id"):
                slot["id"] = entry["id"]
            function = entry.get("function") or {}
            if function.get("name"):
                slot["name"] = function["name"]
            # Concatenated, never replaced: every fragment after the first is a
            # further slice of the same JSON text, and assigning would keep only
            # the last few characters of the arguments.
            slot["arguments"] += function.get("arguments") or ""

    def drain(self) -> tuple[ToolCall, ...]:
        calls = []
        for index in sorted(self._calls):
            slot = self._calls[index]
            if not slot["name"]:
                # No name means nothing a client could execute.
                logger.warning("mlx emitted a tool call with no function name, ignoring")
                continue
            calls.append(
                ToolCall(
                    # A server that sent no id leaves the client without a
                    # handle to pair its result to, so one is minted, as the
                    # Ollama adapter does for every call.
                    id=slot["id"] or f"call_{uuid.uuid4().hex[:24]}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
            )
        self._calls.clear()
        return tuple(calls)


def _sampling_payload(sampling: SamplingOptions | None) -> dict[str, Any]:
    """Top-level OpenAI fields, unlike Ollama's nested `options`. Only what the
    caller actually set, so the server's own defaults stay in force."""
    if sampling is None:
        return {}
    payload: dict[str, Any] = {}
    if sampling.temperature is not None:
        payload["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        payload["top_p"] = sampling.top_p
    if sampling.seed is not None:
        payload["seed"] = sampling.seed
    if sampling.stop:
        payload["stop"] = list(sampling.stop)
    return payload
