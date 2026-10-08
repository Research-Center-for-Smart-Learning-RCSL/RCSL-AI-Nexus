"""The gateway-to-agent wire: lossless both ways, strict on the way in."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.node_agent.wire import (
    EmbeddingRequest,
    Envelope,
    GenerationRequest,
    WireError,
    decode_embedding,
    decode_generation,
    encode_embedding,
    encode_generation,
)

ENVELOPE = Envelope(op_id="op-1", request_id="req-1", payload_hash="v1:abc", store_output=True)
REQUEST = GenerationRequest(
    ref="gemma4:31b-it-q8_0",
    messages=(
        Message(role=MessageRole.SYSTEM, content="be brief"),
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=(ToolCall(id="c1", name="read", arguments='{"path":"a"}'),),
        ),
        Message(role=MessageRole.TOOL, content="file", tool_call_id="c1", name="read"),
    ),
    max_tokens=1024,
    thinking=False,
    tools=(ToolDefinition(name="read", description="", parameters={"type": "object"}),),
    tool_choice=ToolChoice(mode=ToolChoiceMode.FUNCTION, function_name="read"),
    sampling=SamplingOptions(temperature=0.2, top_p=None, stop=("END",), seed=7),
    context_length=262144,
)


def test_a_generation_round_trips_through_json() -> None:
    body = json.loads(json.dumps(encode_generation(REQUEST, ENVELOPE)))

    assert decode_generation(body) == (REQUEST, ENVELOPE)


def test_an_embedding_round_trips_through_json() -> None:
    request = EmbeddingRequest(ref="nomic-embed-text", texts=("a", "b"))
    body = json.loads(json.dumps(encode_embedding(request, ENVELOPE)))

    assert decode_embedding(body) == (request, ENVELOPE)


def _with(**changes: Any) -> dict[str, Any]:
    body = encode_generation(REQUEST, ENVELOPE)
    body.update(changes)
    return body


@pytest.mark.parametrize(
    "body",
    [
        _with(version=2),
        _with(max_tokens=None),
        _with(max_tokens=0),
        _with(max_tokens=True),
        _with(context_length="262144"),
        _with(thinking="false"),
        _with(messages=[]),
        _with(messages=[{"role": "wizard", "content": "x", "tool_calls": []}]),
        _with(op_id=""),
        _with(store_output=None),
        _with(tool_choice={"mode": "sometimes"}),
        _with(sampling={"stop": "END"}),
        _with(tools=[{"name": "t", "description": "", "parameters": "{}"}]),
        "not an object",
    ],
)
def test_anything_malformed_is_refused_not_defaulted(body: Any) -> None:
    with pytest.raises(WireError):
        decode_generation(body)
