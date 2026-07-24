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
        response = client.get("/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_a_401_tells_the_frontend_which_entrance_it_reached() -> None:
    """The UI decides whether a 401 means "reconnect to the tailnet" or "go to
    the login screen", and it learns that from `/me`, which is the very call
    that 401s. Without this it has to guess at the moment it most needs to be
    right."""
    with TestClient(create_tailnet()) as client:
        response = client.get("/me")

    assert response.json()["auth_mode"] == "tailnet"


def test_public_entrance_refuses_a_request_with_no_session_cookie() -> None:
    with TestClient(create_public()) as client:
        response = client.get("/me")

    assert response.status_code == 401


def test_the_public_entrance_mounts_the_login_routes_and_the_tailnet_one_does_not() -> None:
    """A password flow on the tailnet socket would be a second way in that
    does not depend on the tailnet, which is the thing that entrance exists
    to require."""
    with TestClient(create_tailnet()) as client:
        assert (
            client.post("/auth/login", json={"login": "a@b.c", "password": "x"}).status_code == 404
        )

    # On the public entrance the route exists; CSRF is what refuses it here.
    with TestClient(create_public()) as client:
        client.get("/me")
        assert (
            client.post("/auth/login", json={"login": "a@b.c", "password": "x"}).status_code == 403
        )


def test_an_unsafe_request_without_a_csrf_header_is_refused() -> None:
    with TestClient(create_public()) as client:
        # The GET seeds the companion cookie, exactly as the session provider's
        # first call does in the browser.
        client.get("/me")
        response = client.post("/auth/login", json={"login": "a@b.c", "password": "x"})

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_a_mismatched_csrf_header_is_refused() -> None:
    with TestClient(create_public()) as client:
        client.get("/me")
        response = client.post(
            "/auth/login",
            json={"login": "a@b.c", "password": "x"},
            headers={CSRF_HEADER: "not-the-cookie-value"},
        )

    assert response.status_code == 403


def test_the_first_response_issues_a_csrf_cookie_readable_by_scripts() -> None:
    """Not HttpOnly, deliberately: the client has to echo it in a header, and
    that is the entire mechanism. It grants nothing on its own."""
    with TestClient(create_public()) as client:
        response = client.get("/me")

    header = response.headers.get("set-cookie", "")
    assert CSRF_COOKIE in header
    assert "httponly" not in header.lower()


def test_csrf_is_not_installed_on_the_tailnet_entrance() -> None:
    """It has no ambient credential to protect: identity arrives in a header
    that no cross-origin page can cause to be added."""
    with TestClient(create_tailnet()) as client:
        response = client.get("/me")

    assert CSRF_COOKIE not in response.headers.get("set-cookie", "")


def test_an_application_that_installs_no_resolver_refuses_rather_than_defaults() -> None:
    """The placeholder is what makes the choice structural. If it returned
    anything, forgetting the override would be a silent authentication
    bypass rather than an immediate failure."""
    app = FastAPI()
    install_error_handlers(app, envelope="admin")

    @app.get("/whoami")
    async def whoami(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, str]:
        return {"id": actor.id}

    with pytest.raises(NotImplementedError):
        TestClient(app, raise_server_exceptions=True).get("/whoami")
