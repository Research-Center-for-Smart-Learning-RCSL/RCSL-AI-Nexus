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
