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


async def test_num_ctx_is_sent_on_both_load_and_generation(patch_httpx) -> None:
    """The same defect shape as `keep_alive` above, one field along.

    Told nothing, Ollama sizes a runner's KV cache for the model's own declared
    maximum. `gemma4:31b-it-qat` declares 262144, which it predicted at 55.8 GiB
    and evicted every other resident model to fit — on a deployment that never
    sends more than 65536 and had registered 32768 for that model. Three months
    of not sending this were survivable only because `glm-4.7-flash` uses a
    single KV head (PROGRESS.md 2026-08-07).

    Both calls, and for the reason the keep_alive test gives: Ollama keys a
    runner on the options that shape it, so a generation omitting `num_ctx`
    after a load that supplied it starts a second runner at the model's
    maximum — the same allocation, one request later.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, content=ndjson({"message": {"content": "hi"}, "done": True, "eval_count": 1})
        )

    patch_httpx(handler)
    adapter = OllamaAdapter("http://ollama.invalid")

    await adapter.load("gemma4", context_length=32768)
    assert seen["options"]["num_ctx"] == 32768, "the load is what sizes the runner"

    seen.clear()
    async with aclosing(adapter.generate("gemma4", MESSAGES, context_length=32768)) as s:
        async for _ in s:
            pass
    assert seen["options"]["num_ctx"] == 32768, "a generation must not reopen the question"


async def test_an_absent_or_zero_context_length_is_not_sent(patch_httpx) -> None:
    """`context_length` defaults to 0 in the column, and 0 is not a request.

    A row registered before the profile was required carries 0, and sending it
    verbatim would ask Ollama for a zero-length context rather than for its
    default. Absent means "do not say", which is also what a runtime with no
    such control is given.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    patch_httpx(handler)
    adapter = OllamaAdapter("http://ollama.invalid")

    await adapter.load("glm")
    assert "options" not in seen, "nothing was asked for, so nothing is sent"

    seen.clear()
    await adapter.load("glm", context_length=0)
    assert "options" not in seen, "zero is the column default, not an instruction"


async def test_unload_still_evicts_immediately(patch_httpx) -> None:
    """`unload` is the release path the registry depends on, so it keeps its
    own value whatever residency is configured."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    patch_httpx(handler)
    await OllamaAdapter("http://ollama.invalid", keep_alive="-1").unload("glm")
    assert seen["keep_alive"] == 0


async def test_a_numeric_keep_alive_is_sent_as_a_number(patch_httpx) -> None:
    """Ollama parses a string as a Go duration, so `"-1"` is refused with
    `missing unit in duration "-1"` while the number `-1` means forever.

    The environment supplies strings, so the conversion has to happen here. It
    is tested because the failure is invisible: the 400 becomes
    `NoAvailableModelError`, and the caller reads "No model is currently
    available" and goes looking at routing policies.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, content=ndjson({"message": {"content": "hi"}, "done": True, "eval_count": 1})
        )

    patch_httpx(handler)

    async with aclosing(
        OllamaAdapter("http://ollama.invalid", keep_alive="-1").generate("glm", MESSAGES)
    ) as s:
        async for _ in s:
            pass
    assert seen["keep_alive"] == -1
    assert not isinstance(seen["keep_alive"], str), 'the string "-1" is refused by Ollama'

    seen.clear()
    async with aclosing(
        OllamaAdapter("http://ollama.invalid", keep_alive=" 300 ").generate("glm", MESSAGES)
    ) as s:
        async for _ in s:
            pass
    assert seen["keep_alive"] == 300, "surrounding whitespace must not make it a duration"


async def test_residency_reports_resident_and_on_disk_models(patch_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={"models": [{"name": "glm-4.7-flash:q8_0", "size": 38 * 1024**3}]},
            )
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "glm-4.7-flash:q8_0"},
                        {"name": "qwen2.5:7b"},
                    ]
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    patch_httpx(handler)

    residency = await OllamaAdapter("http://ollama.invalid").residency()

    assert residency is not None
    assert residency.resident == {"glm-4.7-flash:q8_0": 38.0}
    assert "qwen2.5:7b" in residency.on_disk
    assert "glm-4.7-flash:q8_0" in residency.on_disk


async def test_residency_answers_under_the_bare_name_for_a_latest_tag(patch_httpx) -> None:
    """Ollama canonicalises `nomic-embed-text` to `nomic-embed-text:latest` in
    its listings while the registry may hold either spelling. Both must match,
    or a model that is plainly resident reads as missing and the observation
    reintroduces the very lie it exists to end."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(
                200, json={"models": [{"name": "nomic-embed-text:latest", "size": 1024**3}]}
            )
        return httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}]})

    patch_httpx(handler)

    residency = await OllamaAdapter("http://ollama.invalid").residency()

    assert residency is not None
    assert "nomic-embed-text" in residency.resident
    assert "nomic-embed-text:latest" in residency.resident
    assert "nomic-embed-text" in residency.on_disk


async def test_residency_is_none_when_the_runtime_cannot_be_asked(patch_httpx) -> None:
    """ "Could not ask" and "asked, nothing loaded" must not read the same: an
    unreachable runtime answering as empty would mark every model unloaded on
    the strength of a network blip."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nobody home")

    patch_httpx(handler)

    assert await OllamaAdapter("http://ollama.invalid").residency() is None


async def test_residency_is_none_on_a_non_200(patch_httpx) -> None:
    patch_httpx(lambda request: httpx.Response(500, json={"error": "boom"}))

    assert await OllamaAdapter("http://ollama.invalid").residency() is None
