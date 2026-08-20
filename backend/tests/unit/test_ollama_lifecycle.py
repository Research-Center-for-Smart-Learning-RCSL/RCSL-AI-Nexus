from __future__ import annotations

import json

import httpx

from app.adapters.runtime.ollama_adapter import OllamaAdapter

pytest_plugins = ("tests.unit.ollama_adapter_fixtures",)


async def test_unload_sends_keep_alive_zero(patch_httpx) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid").unload("llama3")

    assert seen["keep_alive"] == 0, "anything else leaves the model resident"


async def test_load_falls_back_to_embed_for_an_embedding_model(patch_httpx) -> None:
    """An embedding model refuses /api/generate with a 400.

    The refusal must be answered by warming through /api/embed with an empty
    input and the same keep_alive, not surfaced as "no model available" — that
    error sends the operator to the routing policies for a model that is
    sitting right there.
    """
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/generate":
            return httpx.Response(
                400, json={"error": '"nomic-embed-text" does not support generate'}
            )
        return httpx.Response(200, json={"model": "nomic-embed-text", "embeddings": []})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid", keep_alive="-1").load("nomic-embed-text")

    assert [path for path, _ in calls] == ["/api/generate", "/api/embed"]
    assert calls[1][1] == {"model": "nomic-embed-text", "input": [], "keep_alive": -1}


async def test_unload_falls_back_to_embed_for_an_embedding_model(patch_httpx) -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/generate":
            return httpx.Response(
                400, json={"error": '"nomic-embed-text" does not support generate'}
            )
        return httpx.Response(200, json={"model": "nomic-embed-text", "embeddings": []})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid").unload("nomic-embed-text")

    assert calls[1][1]["keep_alive"] == 0, "anything else leaves the model resident"


async def test_load_does_not_touch_embed_for_a_chat_model(patch_httpx) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid").load("llama3")

    assert calls == ["/api/generate"]


async def test_health_is_false_when_the_host_is_unreachable(patch_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    patch_httpx(handler)
    assert await OllamaAdapter("http://ollama.invalid").health() is False
