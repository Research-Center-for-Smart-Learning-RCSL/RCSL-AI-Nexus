"""What crosses the wire between the gateway and a node agent.

The gateway sends the *domain* arguments of a generation, not a runtime
payload: the agent counts the prompt with its own counter and checks it
against its own node before it builds the runtime body itself (final spec §1,
design S5 on #24). Forwarding a ready-made payload would make the agent's
revalidation a check of the gateway's arithmetic.

Decoding is strict. A field of the wrong type is a `WireError` and a 400, never
a default: a default here would be a request the caller did not send.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)

WIRE_VERSION = 1


class WireError(ValueError):
    """The request does not decode; nothing about it is guessed."""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    ref: str
    messages: tuple[Message, ...]
    max_tokens: int
    """Required: the gateway resolves the effective output bound, and the
    agent's guard needs the same figure the gateway admitted against."""
    thinking: bool
    tools: tuple[ToolDefinition, ...]
    tool_choice: ToolChoice | None
    sampling: SamplingOptions | None
    context_length: int


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    ref: str
    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Envelope:
    """The identity every forwarded call carries (final spec §5)."""

    op_id: str
    request_id: str | None
    payload_hash: str | None
    store_output: bool


# -- encode ----------------------------------------------------------------


def encode_generation(request: GenerationRequest, envelope: Envelope) -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        **_envelope(envelope),
        "ref": request.ref,
        "messages": [_message(m) for m in request.messages],
        "max_tokens": request.max_tokens,
        "thinking": request.thinking,
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in request.tools
        ],
        "tool_choice": (
            None
            if request.tool_choice is None
            else {
                "mode": request.tool_choice.mode.value,
                "function_name": request.tool_choice.function_name,
            }
        ),
        "sampling": (
            None
            if request.sampling is None
            else {
                "temperature": request.sampling.temperature,
                "top_p": request.sampling.top_p,
                "stop": list(request.sampling.stop),
                "seed": request.sampling.seed,
            }
        ),
        "context_length": request.context_length,
    }


def encode_embedding(request: EmbeddingRequest, envelope: Envelope) -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        **_envelope(envelope),
        "ref": request.ref,
        "texts": list(request.texts),
    }


def _envelope(envelope: Envelope) -> dict[str, Any]:
    return {
        "op_id": envelope.op_id,
        "request_id": envelope.request_id,
        "payload_hash": envelope.payload_hash,
        "store_output": envelope.store_output,
    }


def _message(message: Message) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "content": message.content,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "name": message.name,
    }


# -- decode ----------------------------------------------------------------


def decode_generation(body: Any) -> tuple[GenerationRequest, Envelope]:
    data = _object(body, "body")
    _version(data)
    request = GenerationRequest(
        ref=_str(data, "ref"),
        messages=tuple(_decode_message(m) for m in _list(data, "messages")),
        max_tokens=_positive_int(data, "max_tokens"),
        thinking=_bool(data, "thinking"),
        tools=tuple(_decode_tool(t) for t in _list(data, "tools")),
        tool_choice=_decode_tool_choice(data.get("tool_choice")),
        sampling=_decode_sampling(data.get("sampling")),
        context_length=_positive_int(data, "context_length"),
    )
    if not request.messages:
        raise WireError("messages must not be empty")
    return request, _decode_envelope(data)


def decode_embedding(body: Any) -> tuple[EmbeddingRequest, Envelope]:
    data = _object(body, "body")
    _version(data)
    texts = _list(data, "texts")
    if not texts or not all(isinstance(t, str) for t in texts):
        raise WireError("texts must be a non-empty list of strings")
    return EmbeddingRequest(ref=_str(data, "ref"), texts=tuple(texts)), _decode_envelope(data)


def _decode_envelope(data: dict[str, Any]) -> Envelope:
    return Envelope(
        op_id=_str(data, "op_id"),
        request_id=_optional_str(data, "request_id"),
        payload_hash=_optional_str(data, "payload_hash"),
        store_output=_bool(data, "store_output"),
    )


def _decode_message(raw: Any) -> Message:
    data = _object(raw, "message")
    try:
        role = MessageRole(_str(data, "role"))
    except ValueError as exc:
        raise WireError(f"unknown message role {data.get('role')!r}") from exc
    calls = tuple(
        ToolCall(
            id=_str(c, "id"),
            name=_str(c, "name"),
            arguments=_str(c, "arguments"),
        )
        for c in (_object(x, "tool call") for x in _list(data, "tool_calls"))
    )
    return Message(
        role=role,
        content=_str(data, "content", empty=True),
        tool_calls=calls,
        tool_call_id=_optional_str(data, "tool_call_id"),
        name=_optional_str(data, "name"),
    )


def _decode_tool(raw: Any) -> ToolDefinition:
    data = _object(raw, "tool")
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        raise WireError("tool parameters must be an object")
    return ToolDefinition(
        name=_str(data, "name"),
        description=_str(data, "description", empty=True),
        parameters=parameters,
    )


def _decode_tool_choice(raw: Any) -> ToolChoice | None:
    if raw is None:
        return None
    data = _object(raw, "tool_choice")
    try:
        mode = ToolChoiceMode(_str(data, "mode"))
    except ValueError as exc:
        raise WireError(f"unknown tool_choice mode {data.get('mode')!r}") from exc
    return ToolChoice(mode=mode, function_name=_optional_str(data, "function_name"))


def _decode_sampling(raw: Any) -> SamplingOptions | None:
    if raw is None:
        return None
    data = _object(raw, "sampling")
    stop = data.get("stop", [])
    if not isinstance(stop, list) or not all(isinstance(s, str) for s in stop):
        raise WireError("sampling.stop must be a list of strings")
    return SamplingOptions(
        temperature=_optional_number(data, "temperature"),
        top_p=_optional_number(data, "top_p"),
        stop=tuple(stop),
        seed=_optional_int(data, "seed"),
    )


def _version(data: dict[str, Any]) -> None:
    if data.get("version") != WIRE_VERSION:
        raise WireError(f"wire version {data.get('version')!r} is not {WIRE_VERSION}")


def _object(raw: Any, what: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WireError(f"{what} must be an object")
    return raw


def _list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise WireError(f"{key} must be a list")
    return value


def _str(data: dict[str, Any], key: str, *, empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not empty and not value):
        raise WireError(f"{key} must be a {'' if empty else 'non-empty '}string")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise WireError(f"{key} must be a string or null")
    return value


def _bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise WireError(f"{key} must be a boolean")
    return value


def _positive_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WireError(f"{key} must be a positive integer")
    return value


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise WireError(f"{key} must be an integer or null")
    return value


def _optional_number(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise WireError(f"{key} must be a number or null")
    return float(value)
