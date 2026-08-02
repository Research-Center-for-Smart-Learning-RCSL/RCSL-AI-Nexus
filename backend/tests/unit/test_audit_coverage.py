"""Authorization failures reach the audit log, and the shapes that must not.

security.md section 12 requires authorization failures to be recorded. Nothing
recorded them until 2026-08-02: `RoleAuthorization.require` raised, the handler
mapped it to 403 and wrote an application-log line, and the audit log — the one
place a refusal is durable and tamper-evident — never heard about it.

These test the handler rather than a use case, because the handler is the whole
point: it is the one place every `NotAuthorizedError` passes through, including
the ones use cases raise directly without consulting `AuthorizationPort`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.adapters.authz.role_authorization import RoleAuthorization
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.user import User
from app.domain.exceptions import NotAuthorizedError
from app.infrastructure.config import get_settings
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.identity import resolve_tailnet_actor
from app.interfaces.http.request_actor import actor_from_request, remember_actor
from tests.unit.fakes import FakeAudit, FakeUsers

ACTOR = Actor(
    id="u1",
    display="someone@example.org",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
    tenant_id="t-research",
)


def build(*, with_audit: bool = True, with_actor: bool = True) -> tuple[FastAPI, FakeAudit]:
    app = FastAPI()
    install_error_handlers(app, envelope="admin")

    audit = FakeAudit()
    if with_audit:
        app.state.audit = audit

    @app.delete("/admin/models/{model_id}")
    async def refuse(request: Request, model_id: str) -> None:
        if with_actor:
            remember_actor(request, ACTOR)
        raise NotAuthorizedError(detail=f"{ACTOR.display} lacks model:write")

    return app, audit


def test_a_refusal_is_recorded_with_who_what_and_from_where() -> None:
    app, audit = build()

    with TestClient(app) as client:
        response = client.delete("/admin/models/m1")

    assert response.status_code == 403

    actor, action, target, outcome, detail = audit.only("authz.denied")
    assert action == "authz.denied"
    assert (actor.id, actor.tenant_id) == ("u1", "t-research")
    assert target == "/admin/models/m1"
    assert outcome == "denied"
    assert detail["method"] == "DELETE"
    # The missing scope is named for the operator. It is in `exc.detail`, which
    # the response body never carries.
    assert "model:write" in detail["reason"]


def test_the_refusal_body_still_says_nothing() -> None:
    """Auditing more must not mean responding with more: the caller learns that
    they were refused and not what they were missing."""
    app, _ = build()

    with TestClient(app) as client:
        body = client.delete("/admin/models/m1").json()

    assert body == {"code": "not_authorized", "message": body["message"]}
    assert "model:write" not in body["message"]


def test_an_entrance_with_no_audit_still_refuses_cleanly() -> None:
    """The gateway's shape. Its database account may write `usage_records` and
    nothing else, so it carries no audit adapter; a 403 there must be an
    ordinary 403 rather than a 500 or a failed write on every request."""
    app, audit = build(with_audit=False)

    with TestClient(app) as client:
        response = client.delete("/admin/models/m1")

    assert response.status_code == 403
    assert audit.rows == []


def test_a_refusal_before_identification_records_nothing() -> None:
    """There is no subject to attribute it to, and inventing one would put a
    fictional actor in the log that an investigation would have to rule out."""
    app, audit = build(with_actor=False)

    with TestClient(app) as client:
        response = client.delete("/admin/models/m1")

    assert response.status_code == 403
    assert audit.rows == []


async def test_the_tailnet_resolver_leaves_the_actor_where_the_handler_looks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half that makes the rest of this file mean anything.

    Everything above hands the handler an actor directly. If a resolver stopped
    calling `remember_actor`, refusals on that entrance would silently stop
    being audited and every other test here would still pass.
    """
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    user = User(
        id="u9",
        login="admin@example.org",
        display_name="Admin",
        role=Role.ADMIN,
        tailscale_login="admin@example.org",
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/me",
            "query_string": b"",
            "headers": [(b"tailscale-user-login", b"admin@example.org")],
        }
    )

    resolved = await resolve_tailnet_actor(
        request,
        users=FakeUsers([user]),
        bootstrap=_NoBootstrap(),
        authz=RoleAuthorization(),
    )

    assert actor_from_request(request) is resolved
    assert resolved.id == "u9"

    get_settings.cache_clear()


class _NoBootstrap:
    """Bootstrap is inert once a user exists, which is the case under test."""

    async def claim(self, tailscale_login: str, display_name: str) -> User | None:
        return None


# --- signing out must not start depending on the database ----------------


class _UnreachableUsers:
    async def get(self, user_id: str) -> User | None:
        raise ConnectionError("pool exhausted")


class _LiveSessions:
    def __init__(self, user_id: str | None) -> None:
        self._user_id = user_id

    async def read(self, session_id: str, now: object) -> object | None:
        if self._user_id is None:
            raise ConnectionError("redis is gone")
        return SimpleNamespace(user_id=self._user_id)


async def test_naming_the_signer_out_never_raises() -> None:
    """Logout has to clear the cookie when everything else is broken.

    Before the sign-out record existed this handler touched no database at all.
    Naming the account for the audit row added a `users.get`, and if that
    raises after `sessions.destroy` has run the response is a 500 with the
    session gone and the cookies still in the browser — on the shared machine
    the endpoint's docstring says it must work for. Both dependencies are
    exercised because either can be the one that is down.
    """
    from app.interfaces.http.routers.auth import _who_is_signing_out

    assert await _who_is_signing_out(_LiveSessions("u1"), _UnreachableUsers(), "s1") is None
    assert await _who_is_signing_out(_LiveSessions(None), _UnreachableUsers(), "s1") is None
