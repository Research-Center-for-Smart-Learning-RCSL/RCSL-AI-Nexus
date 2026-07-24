"""How the two admin entrances differ, exercised over HTTP.

The isolation between them is the design's load-bearing claim, so these test
the wiring rather than the use cases: which resolver each application
installs, which one carries CSRF, and that an application which installed
neither refuses rather than falling through to something permissive.

No database is required. Every case here is decided before a query runs, which
is itself worth knowing: an unauthenticated request must not reach the
database at all.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.domain.entities.actor import Actor
from app.infrastructure.config import get_settings
from app.infrastructure.main_admin_public import create_app as create_public
from app.infrastructure.main_admin_tailnet import create_app as create_tailnet
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.identity import current_actor

CSRF_COOKIE = "__Host-nexus_csrf"
CSRF_HEADER = "X-CSRF-Token"

# The public entrance now runs the trusted-proxy check on every route, not
# only the three login routes, so a request that did not arrive through
# openresty is refused before anything else. These headers are what openresty
# adds; without them a test would be rejected at the perimeter rather than
# reaching the behaviour under test. The secret is the shipped dev placeholder.
PROXY_HEADERS = {
    "X-Nexus-Proxy": "dev-proxy-secret-not-for-production",
    "X-Forwarded-For": "203.0.113.10",
}


@pytest.fixture(autouse=True)
def _production_like_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`AUTH_MODE=dev` substitutes an identity, which is exactly what these
    tests must not have. They run in the mode a deployment runs in."""
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_tailnet_entrance_refuses_a_request_with_no_identity_header() -> None:
    with TestClient(create_tailnet()) as client:
        response = client.get("/admin/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_a_401_tells_the_frontend_which_entrance_it_reached() -> None:
    """The UI decides whether a 401 means "reconnect to the tailnet" or "go to
    the login screen", and it learns that from `/me`, which is the very call
    that 401s. Without this it has to guess at the moment it most needs to be
    right."""
    with TestClient(create_tailnet()) as client:
        response = client.get("/admin/me")

    assert response.json()["auth_mode"] == "tailnet"


def test_public_entrance_refuses_a_request_with_no_session_cookie() -> None:
    with TestClient(create_public()) as client:
        response = client.get("/admin/me", headers=PROXY_HEADERS)

    assert response.status_code == 401


def test_the_public_entrance_refuses_a_request_that_did_not_come_through_the_proxy() -> None:
    """The trusted-proxy check now runs on every route, not only the three
    login routes. A request lacking the shared-secret header is refused at the
    perimeter, before the session check."""
    with TestClient(create_public()) as client:
        response = client.get("/admin/me")

    assert response.status_code == 400
    assert response.json()["code"] == "untrusted_proxy"


def test_the_login_routes_are_mounted_only_on_the_public_entrance() -> None:
    """A password flow on the tailnet socket would be a second way in that
    does not depend on the tailnet, which is the thing that entrance exists
    to require. Asserted against the route table rather than a live POST,
    because both entrances now carry CSRF and a missing route with no token
    returns 403 rather than the 404 that proves absence."""
    assert "/admin/auth/login" in create_public().openapi()["paths"]
    assert "/admin/auth/login" not in create_tailnet().openapi()["paths"]


def test_an_unsafe_request_without_a_csrf_header_is_refused() -> None:
    with TestClient(create_public()) as client:
        # The GET seeds the companion cookie, exactly as the session provider's
        # first call does in the browser.
        client.get("/admin/me", headers=PROXY_HEADERS)
        response = client.post(
            "/admin/auth/login", json={"login": "a@b.c", "password": "x"}, headers=PROXY_HEADERS
        )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_a_mismatched_csrf_header_is_refused() -> None:
    with TestClient(create_public()) as client:
        client.get("/admin/me", headers=PROXY_HEADERS)
        response = client.post(
            "/admin/auth/login",
            json={"login": "a@b.c", "password": "x"},
            headers={CSRF_HEADER: "not-the-cookie-value", **PROXY_HEADERS},
        )

    assert response.status_code == 403


def test_the_first_response_issues_a_csrf_cookie_readable_by_scripts() -> None:
    """Not HttpOnly, deliberately: the client has to echo it in a header, and
    that is the entire mechanism. It grants nothing on its own."""
    with TestClient(create_public()) as client:
        response = client.get("/admin/me", headers=PROXY_HEADERS)

    header = response.headers.get("set-cookie", "")
    assert CSRF_COOKIE in header
    assert "httponly" not in header.lower()


def test_csrf_is_installed_on_the_tailnet_entrance_too() -> None:
    """The first version got this wrong. `tailscale serve` attaches the
    identity header to any request the browser can be made to issue, including
    a cross-origin one, so the entrance does have an ambient credential and
    does need the double-submit guard. A body-less POST is the reachable set."""
    with TestClient(create_tailnet()) as client:
        seed = client.get("/admin/me")
        assert CSRF_COOKIE in seed.headers.get("set-cookie", "")

        refused = client.post("/admin/models/m1/unload", headers={CSRF_HEADER: "wrong"})

    assert refused.status_code == 403
    assert refused.json()["code"] == "csrf_failed"


def test_an_application_that_installs_no_resolver_refuses_rather_than_defaults() -> None:
    """The placeholder is what makes the choice structural. If it returned
    anything, forgetting the override would be a silent authentication
    bypass rather than an immediate failure."""
    app = FastAPI()
    install_error_handlers(app, envelope="admin")

    @app.get("/admin/whoami")
    async def whoami(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, str]:
        return {"id": actor.id}

    with pytest.raises(NotImplementedError):
        TestClient(app, raise_server_exceptions=True).get("/admin/whoami")
