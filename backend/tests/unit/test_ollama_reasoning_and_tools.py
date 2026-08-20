from __future__ import annotations

import json
from contextlib import aclosing

import httpx

from app.adapters.runtime.ollama_adapter import OllamaAdapter
from tests.unit.ollama_adapter_fixtures import (
    MESSAGES,
    ndjson,
)

pytest_plugins = ("tests.unit.ollama_adapter_fixtures",)


async def test_thinking_is_streamed_as_reasoning_not_dropped(patch_httpx) -> None:
    """The failure that made a 93-second answer look like a 500.

    A thinking model leaves `content` empty and fills `thinking` until it is
    done. Reading only `content` produced no chunk at all for the whole
    deliberation, so nothing reached the client, the response headers were
    never sent, and the proxy in front cut the idle socket. The stream has to
    carry reasoning for that silence to end.
    """
    events = [
        {"message": {"content": "", "thinking": "First, "}, "done": False},
        {"message": {"content": "", "thinking": "then."}, "done": False},
        {"message": {"content": "42"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 3},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    chunks = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("glm", MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert "".join(c.reasoning for c in chunks) == "First, then."
    assert "".join(c.delta for c in chunks) == "42", "reasoning must not leak into the answer"
    assert sum(c.token_count for c in chunks) == 3, "eval_count covers thinking tokens too"


async def test_a_generation_that_is_entirely_thinking_still_produces_chunks(patch_httpx) -> None:
    """The exact shape of the 500: the budget is spent before an answer starts.

    There is no answer to show, but chunks must still flow — both so the
    connection stays alive and so the caller can report that the model
    deliberated its way past the ceiling rather than returning a blank bubble.
    """
    events = [
        {"message": {"content": "", "thinking": "still working"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "length", "eval_count": 4096},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    chunks = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("glm", MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert len(chunks) >= 2, "a silent stream is what the proxy killed"
    assert "".join(c.delta for c in chunks) == ""
    assert chunks[-1].finish_reason == "length"


async def test_a_tool_call_cut_off_at_the_ceiling_reports_length_not_tool_calls(
    patch_httpx,
) -> None:
    """The residual half of the truncation bug fixed on 2026-08-09.

    `tool_calls` overrides `stop`, because a successful call-producing
    generation reports `stop` and an agent loop branches on this field alone.
    It must not override `length`: a generation cut off at the ceiling may have
    stopped part way through `arguments`, so the client would be invited to
    execute a JSON fragment — and `/v1/responses` keys `response.incomplete` on
    this value, so the turn would also be reported as a finished one.
    """
    call = {"function": {"name": "sh", "arguments": {"cmd": "ls"}}}
    events = [
        {"message": {"content": "", "tool_calls": [call]}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "length", "eval_count": 12},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    chunks = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("m", MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert chunks[-1].finish_reason == "length"
    # The calls that did arrive are still forwarded; what changes is the reason
    # reported for the turn, not whether the caller sees what was produced.
    assert any(c.tool_calls for c in chunks)


async def test_a_completed_tool_call_still_reports_tool_calls(patch_httpx) -> None:
    """The behaviour the override exists for, pinned so the fix above cannot
    quietly take it away: Ollama ends a call-producing generation with `stop`,
    which stalls an agent loop if forwarded."""
    call = {"function": {"name": "sh", "arguments": {"cmd": "ls"}}}
    events = [
        {"message": {"content": "", "tool_calls": [call]}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 12},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    chunks = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("m", MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert chunks[-1].finish_reason == "tool_calls"


async def test_think_false_is_sent_only_when_thinking_is_disabled(patch_httpx) -> None:
    """`think: true` is never sent, at any setting.

    Ollama refuses it for a model that does not support thinking, so sending it
    to a registry holding both kinds breaks every non-thinking model. Absence
    means "whatever the model does by default", which is the only safe way to
    express "on" across a mixed registry.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, content=ndjson({"message": {"content": "hi"}, "done": True, "eval_count": 1})
        )

    patch_httpx(handler)

    adapter = OllamaAdapter("http://ollama.invalid")

    async with aclosing(adapter.generate("glm", MESSAGES, thinking=True)) as s:
        async for _ in s:
            pass
    assert "think" not in seen, "asking for thinking breaks non-thinking models"

    seen.clear()
    async with aclosing(adapter.generate("glm", MESSAGES, thinking=False)) as s:
        async for _ in s:
            pass
    assert seen["think"] is False

    # Per call, not per adapter: one resident copy serves both kinds of request,
    # so the same instance must be able to answer either way in succession.
    seen.clear()
    async with aclosing(adapter.generate("glm", MESSAGES, thinking=True)) as s:
        async for _ in s:
            pass
    assert "think" not in seen, "the previous call must not have changed the adapter"


async def test_keep_alive_is_sent_on_generation_not_only_on_load(patch_httpx) -> None:
    """The defect this fixes: `load` asked for one residency and the next
    generation silently replaced it with Ollama's own default, because a request
    that omits the field gets the server default rather than the previous value.
    Fourteen reloads in a day, with a configured `10m` that never once applied.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, content=ndjson({"message": {"content": "hi"}, "done": True, "eval_count": 1})
        )

    patch_httpx(handler)
    adapter = OllamaAdapter("http://ollama.invalid", keep_alive="10m")

    async with aclosing(adapter.generate("glm", MESSAGES)) as s:
        async for _ in s:
            pass
    assert seen["keep_alive"] == "10m", "a generation must not fall back to the server default"

    seen.clear()
    await adapter.load("glm")
    assert seen["keep_alive"] == "10m", "load and generate must agree on residency"
