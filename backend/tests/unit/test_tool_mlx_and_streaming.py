from __future__ import annotations

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.domain.entities.chat import (
    CompletionChunk,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
)
from app.domain.exceptions import RuntimeCapabilityError
from app.interfaces.http.schemas.chat_schemas import ChatCompletionRequest
from tests.unit.tool_calling_fixtures import (
    MESSAGES,
    WEATHER,
    drain,
    frames_for,
    sse_lines,
)

pytest_plugins = ("tests.unit.tool_calling_fixtures",)


async def test_mlx_refuses_before_reaching_the_network(monkeypatch) -> None:
    """A refusal that still sends the request would have served the failure it
    exists to prevent, and been indistinguishable in a test that only checks
    the exception."""
    called = {"value": False}

    def record(request: httpx.Request) -> httpx.Response:
        called["value"] = True
        return httpx.Response(200, content=sse_lines({"choices": []}))

    transport = httpx.MockTransport(record)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: original(*a, **{**kw, "transport": transport})
    )

    with pytest.raises(RuntimeCapabilityError):
        await drain(
            MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES, tools=[WEATHER])
        )

    assert called["value"] is False


async def test_mlx_forwards_tools_once_the_deployment_has_verified_it(patch_httpx) -> None:
    """The flag has to actually open the path, or verifying it would leave the
    caller with a refusal they cannot clear and the code permanently dead."""
    sent = patch_httpx(lambda r: httpx.Response(200, content=sse_lines({"choices": []})))

    await drain(
        MlxAdapter("http://mlx.invalid", tool_calling_verified=True).generate(
            "org/model", MESSAGES, tools=[WEATHER]
        )
    )

    assert [t["function"]["name"] for t in sent[0]["tools"]] == ["get_weather"]


async def test_an_ordinary_mlx_chat_is_untouched_by_the_guard(patch_httpx) -> None:
    """MLX's only current use is plain completion. A guard that refused those
    would take the runtime out of service to protect a path nobody is on."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
        )
    )

    chunks = await drain(MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES))

    assert "".join(c.delta for c in chunks) == "hi"


async def test_tool_choice_none_is_not_refused_by_the_guard(patch_httpx) -> None:
    """Withholding the tools *is* "do not call one", so nothing silent can
    happen: the client is not waiting for a call. The guard belongs on the
    branch that puts tools on the wire, not on the presence of the argument."""
    sent = patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
        )
    )

    await drain(
        MlxAdapter("http://mlx.invalid").generate(
            "org/model",
            MESSAGES,
            tools=[WEATHER],
            tool_choice=ToolChoice(mode=ToolChoiceMode.NONE),
        )
    )

    assert "tools" not in sent[0]


async def test_a_tool_call_is_framed_before_the_terminal_frame() -> None:
    """Both arrive on the same chunk. A client that has seen `finish_reason`
    has stopped reading deltas for that choice, so a call framed after it is a
    call the client never sees."""
    frames = await frames_for(
        [
            CompletionChunk(
                delta="",
                tool_calls=(ToolCall(id="c1", name="f", arguments="{}"),),
                finish_reason="tool_calls",
            )
        ]
    )

    call_at = next(i for i, f in enumerate(frames) if f["choices"][0]["delta"].get("tool_calls"))
    terminal_at = next(i for i, f in enumerate(frames) if f["choices"][0]["finish_reason"])
    assert call_at < terminal_at


async def test_tool_call_indexes_run_across_the_stream_not_per_chunk() -> None:
    """A client buffers calls keyed on `index`. Restarting the counter per
    chunk merges two separate calls into one whose name and arguments are both
    concatenations of the pair."""
    frames = await frames_for(
        [
            CompletionChunk(delta="", tool_calls=(ToolCall(id="c1", name="a", arguments="{}"),)),
            CompletionChunk(delta="", tool_calls=(ToolCall(id="c2", name="b", arguments="{}"),)),
        ]
    )

    indexes = [
        call["index"]
        for f in frames
        if f["choices"] and f["choices"][0]["delta"].get("tool_calls")
        for call in f["choices"][0]["delta"]["tool_calls"]
    ]
    assert indexes == [0, 1]


async def test_usage_is_framed_only_when_asked_for() -> None:
    chunks = [
        CompletionChunk(delta="hi", token_count=2),
        CompletionChunk(delta="", finish_reason="stop", token_count=1, prompt_tokens=40),
    ]

    without = await frames_for(chunks)
    assert not any("usage" in f for f in without), (
        "an unrequested empty-choices frame reads as malformed"
    )

    with_usage = await frames_for(chunks, include_usage=True)
    usage = next(f for f in with_usage if "usage" in f)["usage"]
    assert usage == {"prompt_tokens": 40, "completion_tokens": 3, "total_tokens": 43}
    assert with_usage[-1]["usage"], "usage comes after the terminal frame, before [DONE]"


def test_array_content_and_a_tool_message_both_parse() -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": "code",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "run ls"}]},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "sh", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "content": "a.txt", "tool_call_id": "c1"},
            ],
            "tools": [{"type": "function", "function": {"name": "sh", "parameters": {}}}],
        }
    )

    assert request.messages[1].content is None
    assert request.messages[2].tool_call_id == "c1"
    assert request.tools[0].function.name == "sh"


def test_a_tool_message_without_a_call_id_is_refused() -> None:
    """It cannot be paired with anything, so the model would read a result
    attributed to no request it made."""
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {"model": "chat", "messages": [{"role": "tool", "content": "x"}]}
        )


def test_an_image_part_is_refused_rather_than_dropped() -> None:
    """Answering from the text alone would look like the model had seen the
    picture and chosen to ignore it."""
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {
                "model": "vision",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": "http://x/y.png"}}],
                    }
                ],
            }
        )


def test_more_than_one_choice_is_refused() -> None:
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {"model": "chat", "messages": [{"role": "user", "content": "hi"}], "n": 2}
        )


@pytest.mark.parametrize("value", ["END", "User:", "\n\nObservation:", "</tool_call>"])
def test_a_bare_stop_string_is_accepted_whatever_its_length(value) -> None:
    """`max_length=4` on the union capped the *string* branch at four
    characters, because pydantic applies a length rule to every member it fits.
    Every ordinary stop sequence was refused with a 422 about "items", and the
    first version of this test used a three-character value, so it passed."""
    request = ChatCompletionRequest.model_validate(
        {"model": "chat", "messages": [{"role": "user", "content": "hi"}], "stop": value}
    )
    assert request.stop_sequences == (value,)


def test_more_than_four_stop_sequences_is_refused() -> None:
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {
                "model": "chat",
                "messages": [{"role": "user", "content": "hi"}],
                "stop": ["a", "b", "c", "d", "e"],
            }
        )
