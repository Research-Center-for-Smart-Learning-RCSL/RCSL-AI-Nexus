"""The prefix the frontend actually asks for.

Every admin route shipped at the root while `next.config.js` forwarded
`/admin/:path*` **keeping** the prefix and `api-client.ts` prepended `/admin`
to every path. The result was that no call from the browser reached a handler:
the entire management UI 404'd against a stock deployment.

Nothing caught it. Every other test calls the ASGI app directly, so they
exercise handlers and never the contract between the two halves. This file
tests the contract and nothing else, which is why it asserts on the route
table rather than on any behaviour.

Health is deliberately excluded: Compose and the reverse proxy probe it
directly, not through the rewrite.
"""

from __future__ import annotations

import pytest

from app.infrastructure.admin_composition import ADMIN_PREFIX
from app.infrastructure.config import get_settings
from app.infrastructure.main_admin_public import create_app as create_public
from app.infrastructure.main_admin_tailnet import create_app as create_tailnet

ROOT_ROUTES = frozenset({"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"})

# What the frontend asks for, taken from api-client.ts (`API_BASE = '/admin'`)
# plus each feature's api.ts. If a path here stops resolving, a page breaks.
FRONTEND_PATHS = [
    "/admin/me",
    "/admin/users",
    "/admin/api-keys",
    "/admin/models",
    "/admin/nodes",
    "/admin/dashboard",
    "/admin/chat",
    "/admin/assistant",
    "/admin/invitations",
    "/admin/password-resets",
]


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("create", [create_tailnet, create_public], ids=["tailnet", "public"])
def test_every_management_route_is_under_the_prefix(create) -> None:
    stray = sorted(
        path
        for path in create().openapi()["paths"]
        if not path.startswith(ADMIN_PREFIX) and path not in ROOT_ROUTES
    )

    assert stray == [], f"routes outside {ADMIN_PREFIX}: {stray}"


@pytest.mark.parametrize("path", FRONTEND_PATHS)
def test_the_paths_the_frontend_asks_for_exist(path: str) -> None:
    assert path in create_tailnet().openapi()["paths"]


def test_the_login_routes_the_frontend_asks_for_exist() -> None:
    """Only on the public entrance: a password flow on the tailnet socket
    would be a second way in that does not depend on the tailnet."""
    paths = create_public().openapi()["paths"]

    for path in ("/admin/auth/login", "/admin/auth/login/totp", "/admin/auth/logout"):
        assert path in paths

    assert "/admin/auth/login" not in create_tailnet().openapi()["paths"]


def test_health_stays_at_the_root() -> None:
    """Probed by Compose and by the reverse proxy, neither of which goes
    through the rewrite that adds the prefix."""
    for create in (create_tailnet, create_public):
        paths = create().openapi()["paths"]
        assert "/healthz" in paths
        assert "/readyz" in paths
