from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.application.use_cases.capability_availability import assess_availability
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.node import NodeStatus
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import NoAvailableModelError
from app.domain.services.routing_service import RoutingService
from app.shared.clock import FixedClock
from tests.unit.test_routing_service import make_model, make_node

NOW = datetime(2026, 10, 13, tzinfo=UTC)
MODEL = replace(make_model("primary"), observed_at=NOW)
NODE = make_node()
POLICY = RoutingPolicy("chat", (RoutingCandidate("primary", 100),))


def assess(
    models=(MODEL,), nodes=(NODE,), blocked=None, unavailable=frozenset(), policies=(POLICY,)
):
    return {
        c.capability: c
        for c in assess_availability(
            list(policies), list(models), list(nodes), blocked or {}, unavailable, NOW
        )
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"observed_state": None}, "residency_unknown"),
        ({"observed_at": None}, "residency_unknown"),
        ({"observed_at": NOW - timedelta(seconds=91)}, "residency_stale"),
        ({"observed_at": NOW + timedelta(seconds=1)}, "residency_stale"),
        ({"observed_state": ModelState.DOWNLOADED}, "model_not_resident"),
    ],
)
def test_unknown_stale_or_absent_ollama_is_refused_even_without_policy_requirements(
    changes, reason
):
    model = replace(MODEL, **changes)
    with pytest.raises(NoAvailableModelError):
        RoutingService(FixedClock(NOW)).select(POLICY, {model.alias: model}, {NODE.id: NODE})
    assert assess(models=[model])["chat"].reasons == (reason,)


def test_freshness_boundary_and_retry_after_error():
    model = replace(MODEL, state=ModelState.ERROR, observed_at=NOW - timedelta(seconds=90))
    assert assess(models=[model])["chat"].available


def test_mlx_keeps_intent_fallback():
    model = replace(MODEL, runtime=RuntimeKind.MLX, observed_state=None, observed_at=None)
    assert assess(models=[model])["chat"].available


def test_unhealthy_node_is_refused_even_when_policy_omits_requirement():
    assert assess(nodes=[replace(NODE, status=NodeStatus.OFFLINE)])["chat"].reasons == (
        "node_unhealthy",
    )


def test_selected_blocked_primary_is_unavailable_even_with_a_healthy_fallback():
    fallback = replace(MODEL, id="m2", alias="fallback", node_id="n2")
    policy = replace(POLICY, candidates=POLICY.candidates + (RoutingCandidate("fallback", 1),))
    assert assess(blocked={"n1": 1})["chat"].reasons == ("node_operation_unresolved",)
    assert not assess([MODEL, fallback], [NODE, make_node("n2")], {"n1": 1}, policies=[policy])[
        "chat"
    ].available
    assert assess()["chat"].available
    # Residency rejection happens during real selection, so that fallback
    # does work and the rehearsal must agree with it.
    absent = replace(MODEL, observed_state=ModelState.DOWNLOADED)
    assert assess([absent, fallback], [NODE, make_node("n2")], policies=[policy])["chat"].available


def test_selected_missing_adapter_does_not_invent_a_fallback():
    fallback = replace(MODEL, id="m2", alias="fallback")
    policy = replace(POLICY, candidates=POLICY.candidates + (RoutingCandidate("fallback", 1),))
    assert not assess([MODEL, fallback], unavailable=frozenset({MODEL.id}), policies=[policy])[
        "chat"
    ].available


def test_missing_adapter_is_not_available_and_missing_policy_is_not_enabled():
    result = assess(unavailable=frozenset({MODEL.id}))
    assert result["chat"].reasons == ("runtime_unavailable",)
    assert result["code"].reasons == ("no_policy",)
    assert not result["code"].enabled


async def test_endpoint_requires_routing_scope_before_reading_inventory(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.adapters.authz.role_authorization import RoleAuthorization
    from app.domain.entities.actor import Actor, Role, Scope
    from app.infrastructure.availability import AvailabilitySnapshot
    from app.infrastructure.di.shared import _commit_before_response
    from app.interfaces.http.errors import install_error_handlers
    from app.interfaces.http.middleware.identity import current_actor
    from app.interfaces.http.routers import capability_availability as route

    app = FastAPI()
    app.state.authz = RoleAuthorization()
    app.state.runtimes = {}
    app.include_router(route.router, prefix="/admin")
    install_error_handlers(app)
    calls = []

    async def read(*args):
        calls.append(True)
        return AvailabilitySnapshot(NOW, list(assess().values()), {}, False)

    monkeypatch.setattr(route, "read_availability", read)

    async def session():
        yield None

    app.dependency_overrides[_commit_before_response] = session
    actor = Actor("user", "user", Role.USER, "local", scopes=frozenset())
    app.dependency_overrides[current_actor] = lambda: actor
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/admin/capabilities/availability")
        assert denied.status_code == 403
        assert calls == []
        actor = replace(actor, role=Role.ADMIN, scopes=frozenset({Scope.ROUTING_READ}))
        allowed = await client.get("/admin/capabilities/availability")
        assert allowed.status_code == 200
        assert "primary" not in allowed.text
        assert "n1" not in allowed.text
        assert len(calls) == 1


async def test_periodic_metrics_refresh_without_requests_and_failures_keep_old_timestamp(
    monkeypatch,
):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from prometheus_client import CollectorRegistry

    from app.adapters.metrics.prometheus import Metrics
    from app.infrastructure import availability as observation

    registry = CollectorRegistry()
    metrics = Metrics(registry)
    app = SimpleNamespace(state=SimpleNamespace(metrics=metrics, runtimes={}))
    steps = 0

    async def sleep(_):
        nonlocal steps
        steps += 1
        if steps == 4:
            raise asyncio.CancelledError

    class Session:
        async def execute(self, _):
            pass

    @asynccontextmanager
    async def scope():
        yield Session()

    async def read(*_):
        if steps == 3:
            raise OSError("database unreachable")
        capabilities = list(assess(policies=[POLICY] if steps == 1 else []).values())
        return observation.AvailabilitySnapshot(NOW, capabilities, {"n1": 1}, True)

    monkeypatch.setattr(observation.asyncio, "sleep", sleep)
    monkeypatch.setattr(observation, "session_scope", scope)
    monkeypatch.setattr(observation, "read_availability", read)
    with pytest.raises(asyncio.CancelledError):
        await observation.run_availability(app)
    # Policy deletion removes its label; a failed read neither zeroes the
    # unresolved count nor pretends its old successful snapshot is fresh.
    assert registry.get_sample_value("nexus_capability_available", {"capability": "chat"}) is None
    assert registry.get_sample_value("nexus_node_operation_unresolved", {"node": "n1"}) == 1
    assert registry.get_sample_value("nexus_inference_silent_outage") == 1
    assert registry.get_sample_value("nexus_availability_observed_at_seconds") == NOW.timestamp()
