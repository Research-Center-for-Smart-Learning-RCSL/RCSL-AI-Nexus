"""Health endpoints, on all three applications.

Compose health checks, the openresty upstream, and the Phase 2 node
heartbeat all assume these exist and answer without credentials. They must
also stay boring: a liveness probe that reports a version string or a model
list is an information leak on a public endpoint.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.config import get_settings
from app.infrastructure.main_admin_public import create_app as create_admin_public
from app.infrastructure.main_admin_tailnet import create_app as create_admin_tailnet
from app.infrastructure.main_gateway import create_app as create_gateway

APPS = {
    "gateway": create_gateway,
    "admin-tailnet": create_admin_tailnet,
    "admin-public": create_admin_public,
}


@pytest.fixture(params=sorted(APPS), ids=sorted(APPS))
def app(request: pytest.FixtureRequest) -> FastAPI:
    return APPS[request.param]()


def test_healthz_is_reachable_without_credentials(app: FastAPI) -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_failure_when_a_dependency_is_unreachable(monkeypatch) -> None:
    """The previous assertion was `status_code in (200, 503)`, which passed
    against hardcoded booleans that could never produce a 503. Anything gating
    a rollout on this was gating on a constant, so the failing case is what
    needs pinning."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nexus:wrong@127.0.0.1:15499/nope")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()

    try:
        with TestClient(create_gateway()) as client:
            response = client.get("/readyz")
    finally:
        # monkeypatch restores the variables but not the cached Settings built
        # from them. Leaving that in place pointed every later test in the
        # process at an unreachable database.
        get_settings.cache_clear()

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["database"] is False
    get_settings.cache_clear()


def test_health_responses_leak_nothing(app: FastAPI) -> None:
    """No version, hostname, or inventory in a publicly reachable probe."""
    body = TestClient(app).get("/healthz").text.lower()
    for leak in ("version", "0.1.0", "ollama", "qwen", "postgres://", "rcsl.online"):
        assert leak not in body
