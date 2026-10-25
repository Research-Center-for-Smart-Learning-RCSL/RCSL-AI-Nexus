"""How the gateway reports work a maintenance entry stopped (#61).

The agent ends such an attempt with reason `maintenance_interrupted` (sent and
cut off) or `maintenance_before_send` (withheld at the final barrier). The
caller must hear the platform's own `maintenance` code, the one the entrances
give, not a broken stream or a missing model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.domain.exceptions import (
    MaintenanceError,
    NoAvailableModelError,
    StreamInterruptedError,
)

RUNTIME = NodeAgentRuntime("http://agent.invalid", "t" * 40, timeout_s=5)
NOT_DONE = SimpleNamespace(saw_done=False)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("outcome_unknown", "maintenance_interrupted"),
        ("cancelled_unsent", "maintenance_before_send"),
    ],
)
def test_a_stream_stopped_by_maintenance_is_reported_as_maintenance(
    state: str, reason: str
) -> None:
    with pytest.raises(MaintenanceError):
        RUNTIME._settle("op", {"state": state, "reason": reason}, NOT_DONE, True)  # type: ignore[arg-type]


def test_any_other_interruption_stays_an_interrupted_stream() -> None:
    with pytest.raises(StreamInterruptedError):
        RUNTIME._settle(
            "op",
            {"state": "outcome_unknown", "reason": "relay_cancelled"},
            NOT_DONE,
            True,  # type: ignore[arg-type]
        )
    with pytest.raises(NoAvailableModelError):
        RUNTIME._settle("op", {"state": "failed", "reason": "http_500"}, NOT_DONE, False)  # type: ignore[arg-type]


def test_a_lifecycle_operation_stopped_by_maintenance_is_reported_as_maintenance() -> None:
    with pytest.raises(MaintenanceError):
        NodeAgentRuntime._lifecycle_outcome(
            "load", "m", "op", {"state": "cancelled_unsent", "reason": "maintenance_before_send"}
        )
