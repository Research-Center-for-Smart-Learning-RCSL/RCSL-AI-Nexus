"""Metrics emission and the guard on /metrics.

Two properties matter and neither is observable on the dev machine any other
way: that /metrics discloses nothing without the scrape token, and that the
instruments actually move when the process does work. The token guard and the
label cardinality are security properties (the exposition body carries request
rates and model names), so they are pinned here rather than left to the deploy.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from app.adapters.metrics.prometheus import MeteredUsageRepository, Metrics, build_metrics
from app.domain.entities.usage import UsageRecord
from app.infrastructure.config import get_settings
from app.infrastructure.main_admin_public import create_app as create_admin_public
from app.infrastructure.main_admin_tailnet import create_app as create_admin_tailnet
from app.infrastructure.main_gateway import create_app as create_gateway
from app.interfaces.http.middleware.metrics import _route_label

TOKEN = "test-scrape-token"  # noqa: S105 (a test fixture value, not a real secret)
AUTH = {"Authorization": f"Bearer {TOKEN}"}

APPS = {
    "gateway": create_gateway,
    "admin-tailnet": create_admin_tailnet,
    "admin-public": create_admin_public,
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    monkeypatch.setenv("METRICS_SCRAPE_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(params=sorted(APPS), ids=sorted(APPS))
def app(request: pytest.FixtureRequest) -> FastAPI:
    return APPS[request.param]()


def test_scrape_needs_the_token(app: FastAPI) -> None:
    """No token and a wrong token are both 404, not 401: the caller does not
    even learn the endpoint exists."""
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 404
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404

        ok = client.get("/metrics", headers=AUTH)
        assert ok.status_code == 200
        assert ok.headers["content-type"].startswith("text/plain")
        assert "nexus_http_requests_in_progress" in ok.text


def test_disabling_metrics_makes_the_endpoint_vanish(
    monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/metrics", headers=AUTH).status_code == 404


def test_a_served_request_is_counted(app: FastAPI) -> None:
    with TestClient(app) as client:
        client.get("/healthz")
        body = client.get("/metrics", headers=AUTH).text

    # The label is the matched template with method and status, and /healthz has
    # no path params so it is itself.
    assert 'nexus_http_requests_total{method="GET",path="/healthz",status="200"}' in body


def test_the_concurrency_slot_ceiling_is_reported(app: FastAPI) -> None:
    """Every entrance can run inference, so all three carry the slot gauge. The
    default ceiling is 2 (config.max_concurrent_inference)."""
    with TestClient(app) as client:
        body = client.get("/metrics", headers=AUTH).text

    assert "nexus_inference_slots_max 2.0" in body
    assert "nexus_inference_slots_in_use 0.0" in body


def test_a_scanner_hitting_unknown_paths_does_not_explode_cardinality() -> None:
    with TestClient(create_gateway()) as client:
        client.get("/wp-admin")
        client.get("/.env")
        body = client.get("/metrics", headers=AUTH).text

    assert 'path="__unmatched__"' in body
    assert "wp-admin" not in body
    assert ".env" not in body


def test_route_label_reconstructs_the_template_from_path_params() -> None:
    matched = {
        "endpoint": object(),
        "path": "/admin/api-keys/abc123",
        "path_params": {"key_id": "abc123"},
    }
    assert _route_label(matched) == "/admin/api-keys/{key_id}"

    no_params = {"endpoint": object(), "path": "/healthz", "path_params": {}}
    assert _route_label(no_params) == "/healthz"


def test_route_label_buckets_anything_unmatched() -> None:
    # No `endpoint` key: the router never matched, so the raw path is
    # attacker-controlled and must not become a label.
    assert _route_label({"path": "/whatever-a-scanner-tried"}) == "__unmatched__"


class _FakeUsage:
    """Records what it was handed, so the decorator's delegation is checked too."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    async def tokens_used_today(self, api_key_id: str) -> int:
        return 0

    async def last_used_by_key(self) -> dict[str, datetime]:
        return {}

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        return (0, 0)


def _usage(*, tokens: int, completed: bool) -> UsageRecord:
    return UsageRecord(
        id="u1",
        actor_id="a1",
        api_key_id="k1",
        capability="chat",
        model_alias="m",
        tokens=tokens,
        latency_ms=1500,
        completed=completed,
        at=datetime(2026, 7, 25, 12, 0, 0),
        tenant_id="t1",
    )


async def test_metered_usage_emits_from_the_record_and_still_persists() -> None:
    registry = CollectorRegistry()
    metrics = Metrics(registry)
    inner = _FakeUsage()
    repo = MeteredUsageRepository(inner, metrics)

    await repo.record(_usage(tokens=5, completed=True))
    await repo.record(_usage(tokens=3, completed=False))

    # Delegation is intact: the underlying repository still saw both writes.
    assert len(inner.records) == 2

    labels = {"capability": "chat", "model": "m"}
    assert registry.get_sample_value("nexus_inference_tokens_total", labels) == 8
    assert (
        registry.get_sample_value("nexus_inference_requests_total", {**labels, "completed": "true"})
        == 1
    )
    assert (
        registry.get_sample_value(
            "nexus_inference_requests_total", {**labels, "completed": "false"}
        )
        == 1
    )


async def test_slot_gauge_follows_the_limiter() -> None:
    from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter

    limiter = SemaphoreConcurrencyLimiter(3)
    metrics = build_metrics(limiter)

    assert metrics.registry.get_sample_value("nexus_inference_slots_max") == 3
    assert metrics.registry.get_sample_value("nexus_inference_slots_in_use") == 0

    async with limiter.slot():
        assert metrics.registry.get_sample_value("nexus_inference_slots_in_use") == 1
