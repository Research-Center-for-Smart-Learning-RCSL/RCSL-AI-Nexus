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


async def test_a_check_that_answers_false_is_a_failure() -> None:
    """Until 2026-10-09 a probe counted any return as success, so a runtime
    whose `health()` answered False still read as ready."""
    from app.interfaces.http.routers.health import _probe

    async def answers(value: object) -> object:
        return value

    assert await _probe("runtime", answers(False)) == ("runtime", False)
    assert await _probe("runtime", answers(True)) == ("runtime", True)
    assert await _probe("cache", answers(None)) == ("cache", True), "a cache miss is fine"


def test_a_maintenance_hold_does_not_make_an_entrance_unready_for_its_runtime() -> None:
    """#61: the entry releases the runtime on purpose. The health check mailed
    a failure every five minutes of a planned hold until this."""
    from app.interfaces.http.routers.health import readiness

    released = {"database": True, "cache": True, "runtime": False}
    assert readiness(released, maintenance=True)
    assert not readiness(released, maintenance=False)
    assert not readiness({**released, "database": False}, maintenance=True), (
        "a hold never hides a database outage"
    )


async def test_an_unreadable_hold_counts_as_open() -> None:
    from app.interfaces.http.routers import health

    async def broken():  # pragma: no cover - replaced factory
        raise RuntimeError("no database")

    original = health.get_session_factory
    health.get_session_factory = lambda: broken  # type: ignore[assignment]
    try:
        assert await health._maintenance_closed() is False
    finally:
        health.get_session_factory = original
