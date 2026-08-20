from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.adapters.runtime.tool_support import should_send_tools
from app.domain.entities.chat import (
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
)
from app.domain.exceptions import RuntimeCapabilityError
from tests.unit.tool_calling_fixtures import (
    MESSAGES,
    WEATHER,
    drain,
    ndjson,
    sse_lines,
)

pytest_plugins = ("tests.unit.tool_calling_fixtures",)


async def test_tools_reach_ollama_in_the_shape_it_expects(patch_httpx) -> None:
    sent = patch_httpx(
        lambda r: httpx.Response(
            200, content=ndjson({"message": {"content": "ok"}, "done": True, "done_reason": "stop"})
        )
    )

    await drain(
        OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES, tools=[WEATHER])
    )

    tools = sent[0]["tools"]
    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up the weather",
                "parameters": WEATHER.parameters,
            },
        }
    ]


async def test_a_tool_call_gets_an_id_and_a_tool_calls_finish_reason(patch_httpx) -> None:
    """Ollama gives a call no id and ends the turn with `done_reason: stop`.

    Both have to be corrected here. The id is the handle a client pairs its
    result back to, and an agent loop decides whether to run the call on
    `finish_reason` alone — told "stop" it treats the turn as finished, so the
    call is never executed and the conversation stalls.
    """
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "get_weather", "arguments": {"city": "Taipei"}}}
                        ],
                    },
                    "done": True,
                    "done_reason": "stop",
                    "eval_count": 3,
                }
            ),
        )
    )

    chunks = await drain(
        OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES, tools=[WEATHER])
    )

    call = chunks[-1].tool_calls[0]
    assert call.name == "get_weather"
    assert json.loads(call.arguments) == {"city": "Taipei"}
    assert call.id, "a call with no id cannot be paired with its result"
    assert chunks[-1].finish_reason == "tool_calls"


async def test_two_calls_in_one_turn_get_distinct_ids(patch_httpx) -> None:
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "a", "arguments": {}}},
                            {"function": {"name": "b", "arguments": {}}},
                        ],
                    },
                    "done": True,
                    "done_reason": "stop",
                }
            ),
        )
    )

    chunks = await drain(
        OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES, tools=[WEATHER])
    )

    ids = [c.id for c in chunks[-1].tool_calls]
    assert len(set(ids)) == 2, "colliding ids pair a result with the wrong call"


async def test_a_nameless_call_is_dropped_rather_than_forwarded(patch_httpx) -> None:
    """A call with no function name is not executable. Forwarded, it would
    reach the client looking like something it could run."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {"content": "", "tool_calls": [{"function": {"arguments": {}}}]},
                    "done": True,
                    "done_reason": "stop",
                }
            ),
        )
    )

    chunks = await drain(
        OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES, tools=[WEATHER])
    )

    assert chunks[-1].tool_calls == ()


async def test_a_tool_result_round_trips_with_both_pairing_keys(patch_httpx) -> None:
    """The second turn of the loop. Ollama has paired on `tool_name` and
    carries `tool_call_id` on newer builds, so both are sent."""
    sent = patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson({"message": {"content": "23C"}, "done": True, "done_reason": "stop"}),
        )
    )

    history = [
        Message(role=MessageRole.USER, content="weather?"),
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=(ToolCall(id="call_1", name="get_weather", arguments='{"city":"Taipei"}'),),
        ),
        Message(role=MessageRole.TOOL, content="23C", tool_call_id="call_1", name="get_weather"),
    ]
    await drain(OllamaAdapter("http://ollama.invalid").generate("llama3", history))

    assistant, tool = sent[0]["messages"][1], sent[0]["messages"][2]
    # Decoded to an object, because that is the shape Ollama takes.
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"city": "Taipei"}
    # The id this platform minted goes back on the assistant turn. The tool
    # message below cites it, and a build that pairs on ids needs both halves
    # of the pair in the history — the first version omitted it, pointing
    # `tool_call_id` at an id that existed nowhere.
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert tool["role"] == "tool"
    assert tool["tool_name"] == "get_weather"
    assert tool["tool_call_id"] == "call_1"


async def test_malformed_arguments_are_refused_as_a_capability_this_runtime_lacks(
    patch_httpx,
) -> None:
    """The first version sent the raw string and let Ollama decide, so that a
    conversation whose model once emitted malformed JSON stayed replayable.
    Measured false on 0.32.4: Ollama types the field as an object and answers
    400 for *any* string, valid JSON included, so the fallback had no input on
    which it could succeed — and that 400 came back as `no_available_model`,
    whose documented remedy is retry, for a failure that is permanent. A 400
    before the request is sent is the honest answer: the runtime genuinely
    cannot carry these arguments (MLX can), and the caller's remedy is to
    repair or drop the turn, not to replay it forever."""
    sent = patch_httpx(
        lambda r: httpx.Response(
            200, content=ndjson({"message": {"content": "ok"}, "done": True, "done_reason": "stop"})
        )
    )

    history = [
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=(ToolCall(id="c1", name="f", arguments="{not json"),),
        )
    ]
    with pytest.raises(RuntimeCapabilityError):
        await drain(OllamaAdapter("http://ollama.invalid").generate("llama3", history))

    assert sent == [], "refused before any request reached the runtime"


async def test_sampling_reaches_ollama_options_and_omits_what_was_not_set(patch_httpx) -> None:
    sent = patch_httpx(
        lambda r: httpx.Response(
            200, content=ndjson({"message": {"content": "ok"}, "done": True, "done_reason": "stop"})
        )
    )

    await drain(
        OllamaAdapter("http://ollama.invalid").generate(
            "llama3", MESSAGES, sampling=SamplingOptions(temperature=0.0, stop=("END",))
        )
    )

    options = sent[0]["options"]
    assert options["temperature"] == 0.0, (
        "temperature: 0 was accepted and dropped before 2026-08-05"
    )
    assert options["stop"] == ["END"]
    assert "top_p" not in options, "an unset parameter must leave the runtime default alone"
    assert "seed" not in options


def test_tool_choice_none_withholds_the_tools() -> None:
    assert should_send_tools(ToolChoice(mode=ToolChoiceMode.NONE), "ollama") is False


def test_tool_choice_auto_and_unset_send_them() -> None:
    assert should_send_tools(None, "ollama") is True
    assert should_send_tools(ToolChoice(mode=ToolChoiceMode.AUTO), "ollama") is True


@pytest.mark.parametrize("mode", [ToolChoiceMode.REQUIRED, ToolChoiceMode.FUNCTION])
def test_a_choice_the_runtime_cannot_constrain_is_refused(mode) -> None:
    """Refused, not downgraded to auto. A caller who demanded a call and was
    quietly served prose finds out inside their own parser."""
    with pytest.raises(RuntimeCapabilityError):
        should_send_tools(ToolChoice(mode=mode, function_name="f"), "ollama")


async def test_mlx_reassembles_fragmented_tool_call_deltas(patch_httpx) -> None:
    """The OpenAI streaming format splits one call across frames: the first
    carries the id and name, the rest carry slices of the arguments. Assigning
    instead of concatenating would keep only the last slice."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_x",
                                        "function": {"name": "get_weather", "arguments": '{"ci'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ty":'}}]}}
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": '"Taipei"}'}}]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ),
        )
    )

    chunks = await drain(MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES))

    call = chunks[-1].tool_calls[0]
    assert call.id == "call_x"
    assert json.loads(call.arguments) == {"city": "Taipei"}
    assert chunks[-1].finish_reason == "tool_calls"


async def test_mlx_refuses_tools_until_a_deployment_says_it_checked() -> None:
    with pytest.raises(RuntimeCapabilityError):
        await drain(
            MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES, tools=[WEATHER])
        )
