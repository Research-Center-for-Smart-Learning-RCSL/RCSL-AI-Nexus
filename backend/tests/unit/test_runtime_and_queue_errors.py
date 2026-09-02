from __future__ import annotations

import asyncio

import httpx
import pytest

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.exceptions import (
    NoAvailableModelError,
    RuntimeTimeoutError,
    ServerOverloadedError,
    StreamInterruptedError,
)
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from tests.unit.error_precision_fixtures import (
    MESSAGES,
    _patch_client,
    drain,
)

pytest_plugins = ("tests.unit.error_precision_fixtures",)


@pytest.mark.parametrize(("adapter", "ref"), [(OllamaAdapter, "llama3"), (MlxAdapter, "org/model")])
async def test_a_read_timeout_before_any_byte_is_runtime_timeout(adapter, ref, monkeypatch) -> None:
    """The prompt outran the read timeout. The code states the measured remedy:
    an unchanged retry is unlikely to succeed and the caller should send less,
    because a prefill cancelled at the timeout is discarded rather than kept in
    the runtime's prefix cache (measured 2026-08-14). This docstring said the
    opposite until 2026-09-02. `no_available_model` told this caller to back off
    and eventually call an administrator, both wrong."""

    def timing_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _patch_client(monkeypatch, timing_out)

    with pytest.raises(RuntimeTimeoutError) as excinfo:
        await drain(adapter("http://runtime.invalid").generate(ref, MESSAGES))
    assert excinfo.value.code == "runtime_timeout"


@pytest.mark.parametrize(("adapter", "ref"), [(OllamaAdapter, "llama3"), (MlxAdapter, "org/model")])
async def test_a_connect_timeout_stays_no_available_model(adapter, ref, monkeypatch) -> None:
    """The runtime process is down or drowning; retrying into it changes
    nothing an administrator does not. The classification is the split's
    boundary: not every timeout earned the retry-friendly code."""

    def refusing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    _patch_client(monkeypatch, refusing)

    with pytest.raises(NoAvailableModelError) as excinfo:
        await drain(adapter("http://runtime.invalid").generate(ref, MESSAGES))
    assert excinfo.value.code == "no_available_model"


async def test_a_stream_that_ends_without_done_is_stream_interrupted(monkeypatch) -> None:
    """The third remedy class: the caller may hold a partial answer, and
    whether to retry is their idempotence judgement. Also the code the SSE
    error frame carries for a mid-generation death."""

    def half_stream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"message": {"content": "par"}, "done": false}\n')

    _patch_client(monkeypatch, half_stream)

    with pytest.raises(StreamInterruptedError) as excinfo:
        await drain(OllamaAdapter("http://ollama.invalid").generate("llama3", MESSAGES))
    assert excinfo.value.code == "stream_interrupted"


async def test_a_full_queue_refuses_loudly_after_the_wait() -> None:
    """Before 2026-08-05 this caller waited forever in silence — zero bytes,
    no code — and died of their own client timeout, indistinguishable from a
    hung deployment."""
    limiter = SemaphoreConcurrencyLimiter(1, queue_wait_seconds=1)

    async with limiter.slot():
        started = asyncio.get_running_loop().time()
        with pytest.raises(ServerOverloadedError) as excinfo:
            async with limiter.slot():
                pass  # pragma: no cover - the slot is held; entry must fail
        assert excinfo.value.code == "overloaded"
        assert asyncio.get_running_loop().time() - started >= 1


async def test_zero_queue_wait_keeps_the_unbounded_queue() -> None:
    """Zero is the escape hatch back to the old behaviour, so it must actually
    wait rather than refuse instantly."""
    limiter = SemaphoreConcurrencyLimiter(1, queue_wait_seconds=0)

    async with limiter.slot():
        entered = asyncio.Event()

        async def waiter() -> None:
            async with limiter.slot():
                entered.set()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert not entered.is_set(), "the second caller must still be queued"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
