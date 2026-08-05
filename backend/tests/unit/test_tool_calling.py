"""Tool calling, end to end through each layer that touches it.

The agent loop this exists for is a round trip: the model asks for a call, the
*client* runs it, and the result comes back as a message the model has to be
able to pair with its own request. Every property pinned here is one where a
break is silent — the request still succeeds, the model just answers the wrong
conversation, or answers with prose where the caller's parser expects a call.

See docs/architecture/backend.md section 6 and docs/PROGRESS.md 2026-08-05.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import aclosing

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.adapters.runtime.tool_support import should_send_tools
from app.domain.entities.chat import (
    CompletionChunk,
    Message,
    MessageRole,
    SamplingOptions,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.domain.exceptions import NoAvailableModelError, RuntimeCapabilityError
from app.interfaces.http import sse
from app.interfaces.http.schemas.chat_schemas import ChatCompletionRequest

MESSAGES = [Message(role=MessageRole.USER, content="what is the weather")]

WEATHER = ToolDefinition(
    name="get_weather",
    description="Look up the weather",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
)


def ndjson(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def sse_lines(*events: dict) -> bytes:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return (body + "data: [DONE]\n\n").encode()


@pytest.fixture
def patch_httpx(monkeypatch):
    """Captures the outgoing request as well as replaying a response, because
    half of what matters here is what reaches the runtime."""
    sent: list[dict] = []

    def apply(handler):
        def recording(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return handler(request)

        transport = httpx.MockTransport(recording)
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)
        return sent

    return apply


async def drain(generator) -> list[CompletionChunk]:
    chunks = []
    async with aclosing(generator) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return chunks


# --- the Ollama adapter --------------------------------------------------


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


# --- tool_choice ---------------------------------------------------------


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


# --- the MLX adapter -----------------------------------------------------


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


# --- SSE framing ---------------------------------------------------------


async def frames_for(chunks: list[CompletionChunk], **kwargs) -> list[dict]:
    async def generation() -> AsyncIterator[CompletionChunk]:
        for chunk in chunks[1:]:
            yield chunk

    out: list[dict] = []
    async for raw in sse._frames("id", 0, "code", generation(), chunks[0], **kwargs):
        if raw == sse.DONE_SENTINEL:
            continue
        out.append(json.loads(raw.removeprefix("data: ").strip()))
    return out


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


# --- the request schema --------------------------------------------------


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


# --- the finish reason cannot outrun the payload -------------------------


async def test_ollama_does_not_report_tool_calls_it_could_not_forward(patch_httpx) -> None:
    """Every call was dropped for having no name, so there is nothing for the
    client to execute. Reporting `tool_calls` anyway leaves an agent loop
    waiting on a call it was never given, with no content to fall back on —
    the same stall the rewrite exists to prevent, from the other end."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {"content": "", "tool_calls": [{"function": {"arguments": {}}}]},
                    "done": True,
                    "done_reason": "tool_calls",
                }
            ),
        )
    )

    chunks = await drain(
        OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES, tools=[WEATHER])
    )

    assert chunks[-1].tool_calls == ()
    assert chunks[-1].finish_reason == "stop"


async def test_mlx_does_not_report_tool_calls_it_could_not_forward(patch_httpx) -> None:
    """A fragment carrying arguments but never a name accumulates into a slot
    that `drain` discards, so the reason has to be decided after draining
    rather than from having seen the key."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
        )
    )

    chunks = await drain(MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES))

    assert chunks[-1].tool_calls == ()
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.parametrize(
    ("adapter", "ref"),
    [(OllamaAdapter, "llama3"), (MlxAdapter, "org/model")],
)
async def test_a_read_timeout_is_a_domain_error_not_a_500(adapter, ref, monkeypatch) -> None:
    """Nothing above the adapter handles an httpx exception.

    The router's handler only knows `DomainError`, so a timeout escaped as an
    unhandled error with no envelope, or mid-stream as a connection that simply
    stopped without `[DONE]`. It is a reachable outcome rather than a bug: a
    prompt near the context ceiling can take longer to evaluate than the read
    timeout allows, and the runtime sends no bytes at all while it reads.
    """

    def timing_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(timing_out)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(*a, **{**kw, "transport": transport}),
    )

    with pytest.raises(NoAvailableModelError):
        await drain(adapter("http://runtime.invalid").generate(ref, MESSAGES))


async def test_an_unenforceable_choice_is_refused_even_with_no_tools(patch_httpx) -> None:
    """Guarding with `if tools and should_send_tools(...)` short-circuits, so a
    `tool_choice` the runtime cannot honour went unrefused whenever it arrived
    without tools — 200 and prose, where the docs promise a 400."""
    patch_httpx(
        lambda r: httpx.Response(
            200, content=ndjson({"message": {"content": "ok"}, "done": True, "done_reason": "stop"})
        )
    )

    with pytest.raises(RuntimeCapabilityError):
        await drain(
            OllamaAdapter("http://ollama.invalid").generate(
                "llama3", MESSAGES, tool_choice=ToolChoice(mode=ToolChoiceMode.REQUIRED)
            )
        )


# --- findings of the 2026-08-05 review of this feature -------------------


async def test_ollama_calls_repeated_in_the_done_event_are_not_forwarded_twice(
    patch_httpx,
) -> None:
    """On the build this was written against, calls arrive on interim events
    and the done event repeats nothing — observed behaviour, not a contract.
    A build that restated the turn's calls in its done event would have an
    agent execute every one of them twice, and tool calls have side effects,
    so the terminal event is filtered against what was already forwarded."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "sh", "arguments": {"cmd": "rm x"}}}],
                    },
                    "done": False,
                },
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": "sh", "arguments": {"cmd": "rm x"}}}],
                    },
                    "done": True,
                    "done_reason": "stop",
                },
            ),
        )
    )

    chunks = await drain(OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES))

    forwarded = [c for chunk in chunks for c in chunk.tool_calls]
    assert len(forwarded) == 1
    assert chunks[-1].finish_reason == "tool_calls"


async def test_mlx_reports_prompt_tokens_from_the_usage_frame(patch_httpx) -> None:
    """The first version read `completion_tokens` and nothing else, so every
    figure downstream — the usage frame, the non-streaming Usage, the quota
    that has counted prompt tokens since 2026-08-04 — reported 0 prompt tokens
    on this path, and an agent's consumption is mostly prompt."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines(
                {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 512, "completion_tokens": 1}},
            ),
        )
    )

    chunks = await drain(MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES))

    assert chunks[-1].prompt_tokens == 512


async def test_an_mlx_event_carrying_content_and_a_fragment_is_one_token(patch_httpx) -> None:
    """Counting the same event under both fields billed it twice."""
    patch_httpx(
        lambda r: httpx.Response(
            200,
            content=sse_lines(
                {
                    "choices": [
                        {
                            "delta": {
                                "content": "x",
                                "tool_calls": [{"index": 0, "id": "c", "function": {"name": "f"}}],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ),
        )
    )

    chunks = await drain(MlxAdapter("http://mlx.invalid").generate("org/model", MESSAGES))

    assert sum(c.token_count for c in chunks) == 1


@pytest.mark.parametrize(
    ("adapter", "ref"),
    [(OllamaAdapter, "llama3"), (MlxAdapter, "org/model")],
)
async def test_a_connect_timeout_is_also_a_domain_error(adapter, ref, monkeypatch) -> None:
    """`httpx.TimeoutException` covers more than the read timeout, and a
    connect timeout — the runtime process is down — must convert the same way
    or it is a bare 500. The detail differs (it names the connection, not the
    prompt), which this cannot see; what it pins is the classification."""

    def timing_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    transport = httpx.MockTransport(timing_out)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(*a, **{**kw, "transport": transport}),
    )

    with pytest.raises(NoAvailableModelError):
        await drain(adapter("http://runtime.invalid").generate(ref, MESSAGES))


def test_the_deprecated_functions_spelling_is_refused_not_ignored() -> None:
    """`functions` predates `tools` and older client libraries still send it.

    Undeclared, it fell to pydantic's `extra="ignore"` — the identical silent
    failure `tools` itself had until 2026-08-05: 200, prose, and an agent
    stalled waiting for a call that was never requested. Refusing names the
    field the caller should send instead."""
    for legacy in (
        {"functions": [{"name": "f", "parameters": {}}]},
        {"function_call": "auto"},
    ):
        with pytest.raises(ValueError):
            ChatCompletionRequest.model_validate(
                {"model": "chat", "messages": [{"role": "user", "content": "hi"}], **legacy}
            )


def test_tool_calls_on_a_non_assistant_role_are_refused() -> None:
    """The adapters forward the field on whatever role carries it, so a `user`
    message smuggling one would reach the runtime as a shape no chat template
    defines."""
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {
                "model": "chat",
                "messages": [
                    {
                        "role": "user",
                        "content": "hi",
                        "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
                    }
                ],
            }
        )


def test_stream_options_without_a_stream_is_refused() -> None:
    """As OpenAI refuses it: the caller has confused the two paths, and
    silently honouring half the request would hide that."""
    with pytest.raises(ValueError):
        ChatCompletionRequest.model_validate(
            {
                "model": "chat",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "stream_options": {"include_usage": True},
            }
        )


def test_top_p_zero_is_legal() -> None:
    """OpenAI's floor is 0; `gt=0` refused a value every other endpoint takes."""
    request = ChatCompletionRequest.model_validate(
        {"model": "chat", "messages": [{"role": "user", "content": "hi"}], "top_p": 0}
    )
    assert request.top_p == 0.0
