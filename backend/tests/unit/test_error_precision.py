"""The error-precision work of 2026-08-05, each piece pinned.

Three mechanisms, one goal — a caller's failure must be traceable and its
remedy must be stated truthfully:

- the request id, minted per request and carried on the header, every error
  envelope, and the SSE error frame, so a caller can quote the exact log line;
- the split of `no_available_model` into causes whose remedies differ
  (`runtime_timeout`: retry now; `stream_interrupted`: your judgement;
  the original: backoff then administrator);
- the time-boxed debug window, the one condition under which operator detail
  leaves the process, and the bounded queue wait that makes "busy" report
  itself instead of hanging.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.entities.chat import Message, MessageRole
from app.domain.exceptions import (
    NoAvailableModelError,
    RuntimeTimeoutError,
    ServerOverloadedError,
    StreamInterruptedError,
)
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.interfaces.http import request_context
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.request_context import RequestContextMiddleware

MESSAGES = [Message(role=MessageRole.USER, content="hi")]


async def drain(generator) -> None:
    async with aclosing(generator) as stream:
        async for _ in stream:
            pass


def _patch_client(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(*a, **{**kw, "transport": transport}),
    )


# --- the timeout split ----------------------------------------------------


@pytest.mark.parametrize(("adapter", "ref"), [(OllamaAdapter, "llama3"), (MlxAdapter, "org/model")])
async def test_a_read_timeout_before_any_byte_is_runtime_timeout(adapter, ref, monkeypatch) -> None:
    """The prompt outran the read timeout. The code states the measured remedy:
    an immediate retry usually succeeds, because the prompt now sits in the
    runtime's prefix cache. `no_available_model` told this caller to back off
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


# --- the bounded queue ----------------------------------------------------


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


# --- the request id, end to end -------------------------------------------


def _app(envelope: str) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app, envelope=envelope)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/fails")
    async def fails() -> None:
        raise NoAvailableModelError(detail="operator-facing context")

    @app.get("/explodes")
    async def explodes() -> None:
        raise RuntimeError("wiring mistake")

    return app


def test_every_response_carries_a_request_id_header() -> None:
    client = TestClient(_app("openai"))
    response = client.get("/fails")
    assert response.headers["X-Request-Id"].startswith("req_")


def test_the_error_body_repeats_the_header_id() -> None:
    """Bodies get pasted into bug reports; headers do not. The two must be the
    same id or the correlation the pair exists for breaks."""
    client = TestClient(_app("openai"))
    response = client.get("/fails")
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


def test_a_500_is_json_with_an_envelope_and_the_id() -> None:
    """Until 2026-08-05 this was the framework's bare text — the one non-JSON
    body the API produced, on the status where a client most needs to parse."""
    client = TestClient(_app("openai"), raise_server_exceptions=False)
    response = client.get("/explodes")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"].startswith("req_")
    assert response.headers["X-Request-Id"] == body["error"]["request_id"]


def test_detail_stays_out_of_the_body_without_a_debug_window() -> None:
    client = TestClient(_app("openai"))
    body = client.get("/fails").json()
    assert "operator-facing context" not in str(body)


# --- the debug window -----------------------------------------------------


def test_an_open_debug_window_puts_detail_in_the_body() -> None:
    """The one condition under which operator detail leaves the process:
    an administrator opened a time-boxed window on this credential."""
    app = _app("openai")

    @app.get("/fails-debugged")
    async def fails_debugged() -> None:
        request_context.grant_debug_detail(datetime.now(UTC) + timedelta(minutes=5))
        raise NoAvailableModelError(detail="operator-facing context")

    response = TestClient(app).get("/fails-debugged")
    assert response.json()["error"]["detail"] == "operator-facing context"


def test_an_expired_debug_window_reverts_to_the_normal_rule() -> None:
    """Time-boxed has to mean the box closes by itself: an expired window must
    behave exactly like no window, with nobody remembering to turn it off."""
    app = _app("openai")

    @app.get("/fails-expired")
    async def fails_expired() -> None:
        request_context.grant_debug_detail(datetime.now(UTC) - timedelta(minutes=5))
        raise NoAvailableModelError(detail="operator-facing context")

    body = TestClient(app).get("/fails-expired").json()
    assert "operator-facing context" not in str(body)
