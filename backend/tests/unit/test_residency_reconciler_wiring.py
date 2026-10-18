"""The reconciler is off unless asked for, and idle without what it needs (#49)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.infrastructure.config.runtime import RuntimeSettings
from app.infrastructure.residency_reconciler import reconciler_should_run


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deploy must not start loading models nobody asked it to load."""
    monkeypatch.delenv("RESIDENCY_RECONCILER_ENABLED", raising=False)
    assert RuntimeSettings().residency_reconciler_enabled is False


def _app(agents: bool) -> Any:
    return SimpleNamespace(state=SimpleNamespace(runtimes=SimpleNamespace(agents_enabled=agents)))


def _settings(enabled: bool = True, heartbeat: int = 30) -> Any:
    return SimpleNamespace(
        residency_reconciler_enabled=enabled, node_heartbeat_interval_seconds=heartbeat
    )


@pytest.mark.parametrize(
    ("agents", "enabled", "heartbeat", "runs"),
    [
        (True, True, 30, True),
        (True, False, 30, False),
        # Without agents nothing refuses a load while the node is blocked.
        (False, True, 30, False),
        # Without the heartbeat there is never evidence to act on.
        (True, True, 0, False),
    ],
)
def test_runs_only_when_enabled_with_agents_and_heartbeat(
    agents: bool, enabled: bool, heartbeat: int, runs: bool
) -> None:
    assert reconciler_should_run(_app(agents), _settings(enabled, heartbeat)) is runs


async def test_every_pass_outcome_is_counted_and_a_failed_pass_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from prometheus_client import CollectorRegistry

    from app.adapters.metrics.prometheus import Metrics
    from app.application.use_cases.reconcile_residency import PassOutcome, PassResult
    from app.infrastructure import residency_reconciler as wiring

    registry = CollectorRegistry()
    app = SimpleNamespace(state=SimpleNamespace(metrics=Metrics(registry), runtimes={}))
    passes: list[list[PassOutcome] | Exception] = [
        [PassOutcome("n1", PassResult.GAVE_UP), PassOutcome("n2", PassResult.IDLE)],
        OSError("database unreachable"),
        [PassOutcome("n1", PassResult.GAVE_UP)],
    ]

    class Reconciler:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def run_once(self) -> list[PassOutcome]:
            result = passes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    async def sleep(_: float) -> None:
        if not passes:
            raise asyncio.CancelledError

    def sample(outcome: str) -> float | None:
        return registry.get_sample_value("nexus_residency_reconcile_total", {"outcome": outcome})

    settings = SimpleNamespace(
        residency_reconciler_enabled=True, residency_reconciler_interval_seconds=1
    )
    monkeypatch.setattr(wiring, "ReconcileResidency", Reconciler)
    monkeypatch.setattr(wiring, "PostgresNodeSerialisation", lambda *_: None)
    monkeypatch.setattr(wiring.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await wiring.run_residency_reconciler(app, settings)  # type: ignore[arg-type]
    assert sample("gave_up") == 2
    assert sample("idle") == 1
    assert sample("error") == 1
    # Exported at zero from the start, so a first give-up is an increase.
    assert sample("restored") == 0
