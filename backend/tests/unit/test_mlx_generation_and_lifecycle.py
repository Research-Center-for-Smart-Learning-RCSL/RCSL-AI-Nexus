from __future__ import annotations

import json
from contextlib import aclosing

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import (
    MlxAdapter,
)
from app.domain.exceptions import (
    InvalidModelReferenceError,
    ModelNotFoundError,
    ModelStateConflictError,
    NoAvailableModelError,
)
from tests.unit.mlx_adapter_fixtures import (
    MESSAGES,
    REF,
    _chunk,
    sse,
)

pytest_plugins = ("tests.unit.mlx_adapter_fixtures",)


async def test_generate_streams_chunks_and_reconciles_the_token_count(patch_httpx) -> None:
    """The completion_tokens total arrives only in the final usage frame.

    Chunks are counted one apiece as they stream so a disconnect still bills
    something, so the terminal frame must emit only the difference. Emitting the
    whole figure would double-count everything already streamed.
    """
    events = [
        _chunk("Hel"),
        _chunk("lo"),
        _chunk("", finish_reason="stop"),
        {"choices": [], "usage": {"completion_tokens": 5}},
        "[DONE]",
    ]
    patch_httpx(lambda request: httpx.Response(200, content=sse(*events)))

    chunks = []
    async with aclosing(MlxAdapter("http://mlx.invalid").generate(REF, MESSAGES)) as s:
        async for chunk in s:
            chunks.append(chunk)

    assert "".join(c.delta for c in chunks) == "Hello"
    assert sum(c.token_count for c in chunks) == 5, "total must match completion_tokens exactly"
    assert chunks[-1].finish_reason == "stop"


async def test_generate_passes_length_finish_reason_through(patch_httpx) -> None:
    """OpenAI clients decide whether to continue a reply on finish_reason, so a
    truncation must be reported as such rather than flattened to stop."""
    events = [_chunk("hi"), _chunk("", finish_reason="length"), "[DONE]"]
    patch_httpx(lambda request: httpx.Response(200, content=sse(*events)))

    async with aclosing(MlxAdapter("http://mlx.invalid").generate(REF, MESSAGES)) as s:
        chunks = [c async for c in s]

    assert chunks[-1].finish_reason == "length"


async def test_generate_closes_the_upstream_request_on_early_exit(patch_httpx) -> None:
    """The guarantee the whole streaming design rests on.

    If the client goes away and this request is left open, the server carries on
    generating for nobody while holding a concurrency slot.
    """
    closed = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        events = [_chunk(f"tok{i}") for i in range(1000)]

        class TrackingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for event in events:
                    yield (f"data: {json.dumps(event)}\n\n").encode()

            async def aclose(self) -> None:
                closed["value"] = True

        return httpx.Response(200, stream=TrackingStream())

    patch_httpx(handler)

    async with aclosing(MlxAdapter("http://mlx.invalid").generate(REF, MESSAGES)) as s:
        async for _ in s:
            break

    assert closed["value"] is True, "upstream request was left open"


async def test_generate_rejects_a_bad_reference_before_any_request(patch_httpx) -> None:
    called = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["value"] = True
        return httpx.Response(200, content=sse("[DONE]"))

    patch_httpx(handler)

    with pytest.raises(InvalidModelReferenceError):
        async with aclosing(
            MlxAdapter("http://mlx.invalid").generate("../etc/passwd", MESSAGES)
        ) as s:
            async for _ in s:
                pass

    assert called["value"] is False, "validation must happen before the network call"


async def test_generate_raises_when_the_stream_ends_without_a_terminal_frame(patch_httpx) -> None:
    """No [DONE] and no finish_reason: the model was evicted or the read timed
    out. Returning quietly would record a complete generation and report stop."""
    events = [_chunk("Hel"), _chunk("lo")]
    patch_httpx(lambda request: httpx.Response(200, content=sse(*events)))

    with pytest.raises(NoAvailableModelError):
        async with aclosing(MlxAdapter("http://mlx.invalid").generate(REF, MESSAGES)) as s:
            async for _ in s:
                pass


async def test_missing_model_maps_to_a_domain_error(patch_httpx) -> None:
    patch_httpx(lambda request: httpx.Response(404, json={"error": "model not found"}))

    with pytest.raises(ModelNotFoundError):
        async with aclosing(MlxAdapter("http://mlx.invalid").generate(REF, MESSAGES)) as s:
            async for _ in s:
                pass


async def test_unload_is_refused_rather_than_faked(patch_httpx) -> None:
    """mlx_lm.server cannot evict. Reporting success would move the registry to
    DOWNLOADED while the weights are still resident, and the memory budget would
    stop counting a model that is still occupying the host."""
    called = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        called["value"] = True
        return httpx.Response(200, json={})

    patch_httpx(handler)

    with pytest.raises(ModelStateConflictError):
        await MlxAdapter("http://mlx.invalid").unload(REF)

    assert called["value"] is False, "unload must not pretend to reach a runtime that cannot evict"


async def test_load_warms_the_model_with_a_one_token_request(patch_httpx) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    patch_httpx(handler)
    await MlxAdapter("http://mlx.invalid").load(REF)

    assert seen["model"] == REF
    assert seen["max_tokens"] == 1, "a warm-up must not generate more than it has to"


async def test_health_is_false_when_the_host_is_unreachable(patch_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    patch_httpx(handler)
    assert await MlxAdapter("http://mlx.invalid").health() is False
