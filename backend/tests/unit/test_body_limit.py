"""The request body ceiling, and the ordering defect it was written for.

The defect is worth restating because every test here is shaped by it.
Authentication on all three apps is a FastAPI *dependency*, and FastAPI reads
and parses the request body before it resolves dependencies. So an anonymous
caller reached `await request.body()` — an unbounded allocation — before the
check that would have refused them. Measured against the live gateway on
2026-08-07 with a 200 MiB body and no credential.

`test_oversized_body_is_refused_before_authentication` is the regression test
for exactly that, and it is written to fail the way the defect presented: a 422
from the JSON parser rather than a 413 from this middleware.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.domain.exceptions import NotAuthenticatedError
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.body_limit import BodySizeLimitMiddleware

LIMIT = 1024


async def _always_refuses() -> None:
    """Stands in for `authenticate_api_key`: a dependency, like the real one."""
    raise NotAuthenticatedError(detail="no credential")


def build_app(*, envelope: str = "admin", limit: int = LIMIT, guarded: bool = False) -> FastAPI:
    app = FastAPI()
    reached: list[int] = []
    app.state.reached = reached

    dependencies = [Depends(_always_refuses)] if guarded else []

    @app.post("/echo", dependencies=dependencies)
    async def echo(payload: dict[str, str]) -> dict[str, int]:
        reached.append(len(payload.get("filler", "")))
        return {"length": len(payload.get("filler", ""))}

    install_error_handlers(app, envelope=envelope)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=limit, envelope=envelope)
    return app


def _code(response: object) -> str:
    body = response.json()  # type: ignore[attr-defined]
    # The two envelopes nest the code differently; this asserts on the code
    # rather than on which shape the app happened to install.
    return str(body["error"]["code"] if "error" in body else body["code"])


def test_body_under_the_limit_is_served() -> None:
    app = build_app()
    client = TestClient(app)
    response = client.post("/echo", json={"filler": "x" * 100})
    assert response.status_code == 200
    assert app.state.reached == [100]


def test_declared_content_length_over_the_limit_is_refused() -> None:
    app = build_app()
    response = TestClient(app).post("/echo", json={"filler": "x" * (LIMIT * 4)})
    assert response.status_code == 413
    assert _code(response) == "request_too_large"
    # The point of the declared-length path: the handler never ran, so the
    # body was never read into memory.
    assert app.state.reached == []


def test_oversized_body_is_refused_before_authentication() -> None:
    """The regression test for the ordering defect.

    Before the middleware existed this returned 422 — FastAPI parsed the body,
    failed on the JSON, and reported that, all before the dependency that
    refuses an anonymous caller ever ran. A 401 would be an improvement and is
    still not what should happen: the bytes must be refused before either
    check, because both of them are behind the allocation.
    """
    app = build_app(envelope="openai", guarded=True)
    response = TestClient(app).post(
        "/echo",
        content=b"\x00" * (LIMIT * 4),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert _code(response) == "request_too_large"


def test_small_body_still_reaches_the_authentication_dependency() -> None:
    """The middleware must not become the answer to every refusal.

    A request under the ceiling has to reach the dependency and be refused by
    it, or the test above would also pass with a middleware that rejected
    everything.
    """
    response = TestClient(build_app(envelope="openai", guarded=True)).post(
        "/echo", json={"filler": "x"}
    )
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


def test_chunked_body_with_no_content_length_is_refused() -> None:
    """The path a declared length cannot guard.

    A generator body makes httpx send `Transfer-Encoding: chunked` with no
    `Content-Length`, so the fast path sees nothing and the counting receive
    is the only thing between this and an unbounded read.
    """

    def chunks() -> Iterator[bytes]:
        for _ in range(8):
            yield b"y" * (LIMIT // 2)

    app = build_app()
    response = TestClient(app).post(
        "/echo", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert _code(response) == "request_too_large"
    assert app.state.reached == []


def test_a_lying_content_length_does_not_buy_a_larger_body() -> None:
    """`Content-Length` is the caller's claim, not a measurement.

    Declaring a small body and sending a large one passes the fast path, so
    the counter has to be what stops it. Sent chunked with a hand-written
    header, since httpx would otherwise compute an honest one.
    """

    def chunks() -> Iterator[bytes]:
        yield b"z" * (LIMIT * 4)

    app = build_app()
    response = TestClient(app).post(
        "/echo",
        content=chunks(),
        headers={"Content-Type": "application/json", "Content-Length": "10"},
    )
    assert response.status_code == 413
    assert _code(response) == "request_too_large"
    assert app.state.reached == []


def test_a_malformed_content_length_falls_through_to_the_counter() -> None:
    """A header that is not a number says nothing about the size.

    It must not be trusted as zero, and it must not be a rejection of its own:
    either would make a malformed header a different outcome from a missing
    one, when neither carries information.
    """

    def chunks() -> Iterator[bytes]:
        yield b"q" * (LIMIT * 4)

    app = build_app()
    response = TestClient(app).post(
        "/echo",
        content=chunks(),
        headers={"Content-Type": "application/json", "Content-Length": "not-a-number"},
    )
    assert response.status_code == 413
    assert _code(response) == "request_too_large"


def test_the_openai_envelope_is_used_on_the_gateway_shape() -> None:
    response = TestClient(build_app(envelope="openai")).post(
        "/echo", json={"filler": "x" * (LIMIT * 4)}
    )
    body = response.json()
    # Not `api_error`, which is what `handle_unanticipated` sends for a 500 and
    # what an absent 413 used to fall through to. A client library reading this
    # field must not be told a request it has to change is a server fault it
    # should retry.
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "request_too_large"
    # Never the operator-facing detail, which names the platform's own ceiling.
    assert "detail" not in body["error"]


def test_the_counter_is_per_request_not_per_middleware() -> None:
    """One middleware object serves every request.

    A counter held on the instance would accumulate across requests, so the
    third small request would be refused for the size of the first two. This
    is the test that fails if `received` moves out of the closure.
    """
    app = build_app()
    client = TestClient(app)
    for _ in range(5):
        assert client.post("/echo", json={"filler": "x" * (LIMIT // 2)}).status_code == 200
    assert app.state.reached == [LIMIT // 2] * 5


def test_a_streaming_response_passes_through_intact() -> None:
    """The wrapper on the *send* side must not touch a response it is not refusing.

    `guarded_send` exists only to drop what the application emits after a
    rejection, and it sits on every response including the streamed ones this
    gateway exists to serve. A wrapper that swallowed, reordered or coalesced
    chunks would leave every rejection test above passing and break the one
    thing the platform is for — the failure `metrics.py` chose pure ASGI to
    avoid, reintroduced one middleware later.
    """
    app = FastAPI()

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            for i in range(5):
                yield f"chunk-{i}\n".encode()

        return StreamingResponse(chunks(), media_type="text/event-stream")

    install_error_handlers(app, envelope="openai")
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=LIMIT, envelope="openai")

    with TestClient(app).stream("GET", "/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        received = [line for line in response.iter_lines() if line]

    # Every chunk, in order, none merged away.
    assert received == [f"chunk-{i}" for i in range(5)]


def test_a_non_positive_ceiling_is_a_wiring_error() -> None:
    with pytest.raises(ValueError):
        BodySizeLimitMiddleware(FastAPI(), max_bytes=0)
