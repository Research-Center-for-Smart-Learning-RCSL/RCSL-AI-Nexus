from __future__ import annotations

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.entities.chat import (
    ToolChoice,
    ToolChoiceMode,
)
from app.domain.exceptions import NoAvailableModelError, RuntimeCapabilityError
from app.interfaces.http.schemas.chat_schemas import ChatCompletionRequest
from tests.unit.tool_calling_fixtures import (
    MESSAGES,
    WEATHER,
    drain,
    ndjson,
    sse_lines,
)

pytest_plugins = ("tests.unit.tool_calling_fixtures",)


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
