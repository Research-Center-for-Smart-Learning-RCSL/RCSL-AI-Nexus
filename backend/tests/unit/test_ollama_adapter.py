"""Ollama adapter, against a stubbed transport.

No Ollama required: httpx.MockTransport replays recorded NDJSON, which lets
the parsing and lifecycle rules be pinned without a GPU in the loop.

The cases here are the ones that are invisible until they matter: whether the
upstream request is actually closed on disconnect, and whether token counts
are double-counted at the end of a stream.
"""

from __future__ import annotations

import json
from contextlib import aclosing

import httpx
import pytest

from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.entities.chat import Message, MessageRole
from app.domain.exceptions import InvalidModelReferenceError, ModelNotFoundError

MESSAGES = [Message(role=MessageRole.USER, content="hello")]


def ndjson(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


@pytest.fixture
def patch_httpx(monkeypatch):
    def apply(handler):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", patched)

    return apply


async def test_generate_streams_chunks_and_reconciles_the_token_count(patch_httpx) -> None:
    """Ollama reports eval_count only at the end.

    Chunks are counted one apiece as they arrive so a disconnect still bills
    something, so the final event must emit only the difference. Emitting
    eval_count itself would double-count everything already streamed.
    """
    events = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 5},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    chunks = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert "".join(c.delta for c in chunks) == "Hello"
    assert sum(c.token_count for c in chunks) == 5, "total must match eval_count exactly"
    assert chunks[-1].finish_reason == "stop"


async def test_generate_closes_the_upstream_request_on_early_exit(patch_httpx) -> None:
    """The guarantee the whole streaming design rests on.

    If the client goes away and this request is left open, Ollama carries on
    generating for nobody while holding a concurrency slot.
    """
    closed = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        events = [{"message": {"content": f"tok{i}"}, "done": False} for i in range(1000)]

        class TrackingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for event in events:
                    yield (json.dumps(event) + "\n").encode()

            async def aclose(self) -> None:
                closed["value"] = True

        return httpx.Response(200, stream=TrackingStream())

    patch_httpx(handler)

    async with aclosing(OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES)) as s:
        async for _ in s:
            break

    assert closed["value"] is True, "upstream request was left open"


async def test_generate_rejects_a_bad_reference_before_any_request(patch_httpx) -> None:
    called = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["value"] = True
        return httpx.Response(200, content=ndjson({"done": True}))

    patch_httpx(handler)

    with pytest.raises(InvalidModelReferenceError):
        async with aclosing(
            OllamaAdapter("http://ollama.invalid").generate("llama3; rm -rf /", MESSAGES)
        ) as s:
            async for _ in s:
                pass

    assert called["value"] is False, "validation must happen before the network call"


async def test_pull_yields_progress_from_the_ndjson_stream(patch_httpx) -> None:
    events = [
        {"status": "pulling manifest"},
        {"status": "downloading", "completed": 50, "total": 200},
        {"status": "success"},
    ]
    patch_httpx(lambda request: httpx.Response(200, content=ndjson(*events)))

    progress = []
    async with aclosing(OllamaAdapter("http://ollama.invalid").pull("llama3")) as s:
        async for item in s:
            progress.append(item)

    assert [p.status for p in progress] == ["pulling manifest", "downloading", "success"]
    assert progress[1].fraction == 0.25


async def test_missing_model_maps_to_a_domain_error(patch_httpx) -> None:
    patch_httpx(lambda request: httpx.Response(404, json={"error": "model not found"}))

    with pytest.raises(ModelNotFoundError):
        async with aclosing(
            OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES)
        ) as s:
            async for _ in s:
                pass


async def test_unload_sends_keep_alive_zero(patch_httpx) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid").unload("llama3")

    assert seen["keep_alive"] == 0, "anything else leaves the model resident"


async def test_health_is_false_when_the_host_is_unreachable(patch_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    patch_httpx(handler)
    assert await OllamaAdapter("http://ollama.invalid").health() is False
