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

import json
from contextlib import aclosing

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from app.adapters.authz.role_authorization import RoleAuthorization
from app.domain.entities.actor import Role
from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.user import User
from app.domain.exceptions import (
    ContextTooLongError,
    NoAvailableModelError,
    QuotaExceededError,
)
from app.interfaces.http.errors import error_response, install_error_handlers
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


def _quota_body(**kwargs: object) -> tuple[dict, dict]:
    """Rendered through `error_response` rather than a route, because that is
    the seam middleware uses and it is the one a route would exercise anyway."""
    exc = QuotaExceededError(detail="key k used 9", **kwargs)
    response = error_response(exc, envelope="openai")
    return json.loads(bytes(response.body)), dict(response.headers)


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


class _NoBootstrap:
    """Bootstrap is inert once a user exists, which is the case under test."""

    async def claim(self, tailscale_login: str, display_name: str) -> User | None:
        return None


def _too_long() -> ContextTooLongError:
    return ContextTooLongError(
        detail="operator-facing context",
        estimated=99429,
        limit=98304,
        composition="~97800 in 132 messages (largest ~60005, 60% of the whole)",
    )
