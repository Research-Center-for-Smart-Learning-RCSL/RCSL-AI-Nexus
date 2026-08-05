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
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.domain.entities.actor import Role
from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.user import User
from app.domain.exceptions import (
    NoAvailableModelError,
    RuntimeTimeoutError,
    ServerOverloadedError,
    StreamInterruptedError,
)
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.config import get_settings
from app.interfaces.http import request_context
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.identity import resolve_tailnet_actor
from app.interfaces.http.request_context import RequestContextMiddleware
from tests.unit.fakes import FakeUsers

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


class _Body(BaseModel):
    """Module scope deliberately. Declared inside `_app`, FastAPI cannot
    resolve the annotation and reads `payload` as a *query* parameter, so the
    422 is about a missing query field and the test never exercises a body."""

    minutes: int


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

    @app.post("/validates")
    async def validates(payload: _Body) -> None:
        raise AssertionError("unreachable: the body never validates in these tests")

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


# --- a malformed request looks like every other error ---------------------
#
# FastAPI answers validation with `{"detail": [...]}`, its own shape. The
# gateway was given the OpenAI envelope on 2026-08-05 because client libraries
# read `error.message`; the admin entrances kept the raw shape until later the
# same day, which left a validation failure as the one admin error carrying no
# `code` and — once the request id existed — no id to quote either.


def test_the_gateway_renders_a_malformed_request_in_its_own_envelope() -> None:
    body = TestClient(_app("openai")).post("/validates", json={"minutes": "soon"}).json()

    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["request_id"].startswith("req_")
    # Pydantic's summary names the field and the rule. It describes the
    # caller's own request, so there is nothing here to withhold.
    assert "minutes" in body["error"]["message"]


def test_the_admin_entrances_render_one_in_theirs() -> None:
    """The flat shape, with the two keys every other admin error carries.

    Before this, `messageFor` in the frontend read `body.message` and then
    `body.detail` *if it were a string* — pydantic's is a list, so both fell
    through and the operator was shown "Request failed with status 422." in
    place of a message that had already named the field.
    """
    response = TestClient(_app("admin")).post("/validates", json={"minutes": "soon"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request"
    assert "minutes" in body["message"]
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_the_admin_document_advertises_the_422_it_actually_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The document and the handler are two places, and they drifted apart the
    moment the handler changed.

    FastAPI synthesises a 422 of its own `HTTPValidationError` for every route
    with a body, so adding the admin envelope silently made the OpenAPI
    document describe a shape the server no longer sends — and it was the
    generated frontend types, committed in the same change as the drift check
    itself, that carried the false description. Nothing could catch it: the
    contract file compares schemas against the document, and here the document
    was the wrong one.
    """
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    from app.infrastructure.main_admin_tailnet import create_app

    spec = create_app().openapi()
    bodies = {
        path: operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
        for path, methods in spec["paths"].items()
        for operation in methods.values()
        if "422" in operation.get("responses", {})
    }
    assert bodies, "no route advertises a 422; this test would pass vacuously"
    assert set(bodies.values()) == {"#/components/schemas/AdminErrorResponse"}

    declared = set(spec["components"]["schemas"]["AdminErrorResponse"]["properties"])
    sent = TestClient(_app("admin")).post("/validates", json={"minutes": "soon"}).json()
    assert set(sent) <= declared, f"the handler sends keys the document omits: {set(sent) - declared}"

    get_settings.cache_clear()


def test_neither_entrance_still_answers_with_fastapis_own_shape() -> None:
    """The defect stated directly: a bare `detail` list is what both used to
    return, and it is what a regression would look like."""
    for envelope in ("openai", "admin"):
        body = TestClient(_app(envelope)).post("/validates", json={"minutes": "soon"}).json()
        assert not isinstance(body.get("detail"), list), envelope


# --- the window on the *user*, from the stored column outward -------------
#
# The two tests above hand `grant_debug_detail` a value directly, which tests
# the consumer and nothing about who supplies it. That is the shape the user
# half shipped in: `identity.py` read `user.debug_logging_until` and granted on
# it, `UserResponse` exposed it, the frontend displayed it — and no code path
# could set it, for twelve days, looking finished from every side. These drive
# the resolver, so the column and the response body are joined by a test rather
# than by inspection.


def _resolver_app(user: User) -> FastAPI:
    app = _app("admin")

    @app.get("/fails-as-user")
    async def fails_as_user(request: Request) -> None:
        await resolve_tailnet_actor(
            request,
            users=FakeUsers([user]),  # type: ignore[arg-type]
            bootstrap=_NoBootstrap(),  # type: ignore[arg-type]
            authz=RoleAuthorization(),
        )
        raise NoAvailableModelError(detail="operator-facing context")

    return app


def _admin(**overrides: object) -> User:
    fields: dict[str, object] = {
        "id": "u9",
        "login": "admin@example.org",
        "display_name": "Admin",
        "role": Role.ADMIN,
        "tailscale_login": "admin@example.org",
    }
    fields.update(overrides)
    return User(**fields)  # type: ignore[arg-type]


HEADERS = {"Tailscale-User-Login": "admin@example.org"}


def test_an_open_window_on_the_user_row_reaches_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case the API-key window cannot cover: the management UI carries no
    API key, so an administrator debugging their own admin session is
    identified by this row and nothing else."""
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    user = _admin(debug_logging_until=datetime.now(UTC) + timedelta(minutes=30))
    body = TestClient(_resolver_app(user)).get("/fails-as-user", headers=HEADERS).json()

    # The admin envelope is the flat shape, which is the one an administrator
    # debugging the management UI actually receives.
    assert body["detail"] == "operator-facing context"
    get_settings.cache_clear()


def test_a_user_with_no_window_gets_the_normal_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same request against the same resolver, differing only in the
    column — so a resolver that granted unconditionally would fail here rather
    than pass both."""
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    body = TestClient(_resolver_app(_admin())).get("/fails-as-user", headers=HEADERS).json()

    assert "operator-facing context" not in str(body)
    get_settings.cache_clear()


class _NoBootstrap:
    """Bootstrap is inert once a user exists, which is the case under test."""

    async def claim(self, tailscale_login: str, display_name: str) -> User | None:
        return None
