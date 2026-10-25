"""The maintenance coordinator carrying an entry out (P4 on #61).

Against in-memory operations with the SQL repository's rules and a scripted
node agent: the order of a node's phases, the snapshot that is never replaced,
a reset that is asked again under the same id, failures that keep the
platform closed, a hold lifted underneath, and a lease another coordinator
takes over.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.application.use_cases.maintenance_coordinator import (
    SNAPSHOT_TRIES,
    MaintenanceCoordinator,
)
from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance import MaintenanceState
from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    NodeStep,
    OperationStatus,
    StepPhase,
    StepStatus,
)
from app.domain.ports.node_control_port import NodeControlError, NodeControlPort
from tests.unit.fakes import FakeMaintenance, FakeMaintenanceOperations

GEMMA = {
    "name": "gemma4:31b-it-q8_0",
    "model": "gemma4:31b-it-q8_0",
    "digest": "d" * 64,
    "size": 36_000_000_000,
    "size_vram": 36_000_000_000,
    "context_length": 262144,
    "expires_at": "2318-01-01T00:00:00Z",
    "details": {"family": "gemma4"},
    "irrelevant": "dropped",
}


class Agent:
    """One node agent, answering as scripted."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.resident: list[dict[str, Any]] | None = [GEMMA]
        self.quiescent = True
        self.reset_refusal: NodeControlError | None = None
        self.reset_ids: list[str] = []
        self.accounting = "resolved"

    async def interrupt(self, epoch: int) -> dict[str, Any]:
        self.calls.append(f"interrupt:{epoch}")
        return {"epoch": epoch, "interrupted": ["op-1"], "quiescent": self.quiescent}

    async def residency(self) -> list[dict[str, Any]] | None:
        self.calls.append("residency")
        return None if self.resident is None else list(self.resident)

    async def reset(self, epoch: int, reset_id: str, *, operator: str) -> dict[str, Any]:
        self.calls.append(f"reset:{epoch}")
        self.reset_ids.append(reset_id)
        if self.reset_refusal is not None:
            raise self.reset_refusal
        self.resident = []
        return {"reset_id": reset_id, "accounting": self.accounting, "resolved": ["op-1"]}


class Store(FakeMaintenanceOperations):
    """The coordinator's store: the operations, the hold and the audit."""

    def __init__(self, hold: FakeMaintenance) -> None:
        super().__init__()
        self.maintenance = hold
        self.audited: list[tuple[AuditAction, str, str, dict[str, str] | None]] = []

    async def hold(self) -> MaintenanceState:
        return self.maintenance.state

    async def audit(
        self,
        action: AuditAction,
        *,
        target: str,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None:
        self.audited.append((action, target, outcome, detail))


async def entered(*nodes: str) -> tuple[Store, MaintenanceOperation]:
    hold = FakeMaintenance()
    state = await hold.close(changed_by="admin", message=None, expected_return_at=None)
    assert state is not None
    store = Store(hold)
    operation = await store.create_entry(
        epoch=state.epoch, requested_by="admin", node_ids=list(nodes)
    )
    return store, operation


def coordinator(
    store: Store, agents: dict[str, Agent], owner: str = "c1"
) -> MaintenanceCoordinator:
    async def control_for(node_id: str) -> NodeControlPort | None:
        return agents.get(node_id)

    return MaintenanceCoordinator(store, control_for, owner=owner, max_attempts=3)


def step(store: Store, node_id: str = "n1") -> NodeStep:
    operation = list(store.operations.values())[-1]
    return next(s for s in operation.steps if s.node_id == node_id)


def status(store: Store) -> OperationStatus:
    return list(store.operations.values())[-1].status


async def test_a_node_is_interrupted_snapshotted_reset_and_verified_empty() -> None:
    store, _ = await entered("n1")
    agent = Agent()

    assert await coordinator(store, {"n1": agent}).run_once()

    assert agent.calls == ["interrupt:1", "residency", "reset:1", "residency"]
    done = step(store)
    assert (done.phase, done.status) == (StepPhase.VERIFIED, StepStatus.DONE)
    assert done.snapshot == [{k: v for k, v in GEMMA.items() if k != "irrelevant"}]
    assert done.interrupt is not None and done.interrupt["interrupted"] == ["op-1"]
    assert done.accounting == "resolved"
    assert done.verification == {"resident": [], "fresh": True}
    assert status(store) is OperationStatus.SUCCEEDED
    actions = [a[0] for a in store.audited]
    assert actions == [AuditAction.MAINTENANCE_NODE_CLEARED, AuditAction.MAINTENANCE_ENTRY_CLEARED]
    assert store.audited[0][3] is not None and store.audited[0][3]["snapshot"] == GEMMA["name"]


async def test_nodes_are_carried_independently_and_one_failure_fails_the_entry() -> None:
    store, _ = await entered("n1", "n2")
    good, bad = Agent(), Agent()
    bad.resident = [GEMMA]
    bad.reset_refusal = NodeControlError(
        "restart failed", status=502, refused="restart_failed", body={}
    )

    await coordinator(store, {"n1": good, "n2": bad}).run_once()

    assert step(store, "n1").status is StepStatus.DONE
    failed = step(store, "n2")
    assert (failed.phase, failed.status) == (StepPhase.SNAPSHOTTED, StepStatus.FAILED)
    assert failed.reset_id is None, "a failed restart is retried as a new restart"
    assert status(store) is OperationStatus.FAILED
    assert AuditAction.MAINTENANCE_ENTRY_FAILED in [a[0] for a in store.audited]


async def test_an_unanswered_reset_is_asked_again_under_the_same_id() -> None:
    store, _ = await entered("n1")
    agent = Agent()
    agent.reset_refusal = NodeControlError(
        "supervisor did not answer", status=503, refused="supervisor_unanswered"
    )
    coord = coordinator(store, {"n1": agent})

    await coord.run_once()
    first = step(store)
    assert (first.phase, first.attempts) == (StepPhase.SNAPSHOTTED, 1)

    agent.reset_refusal = None
    await coord.run_once()

    assert len(set(agent.reset_ids)) == 1, agent.reset_ids
    assert step(store).status is StepStatus.DONE


async def test_the_first_snapshot_is_never_replaced() -> None:
    store, _ = await entered("n1")
    agent = Agent()
    agent.reset_refusal = NodeControlError("busy", status=409, refused="node_not_quiescent")
    coord = coordinator(store, {"n1": agent})

    await coord.run_once()  # interrupt, snapshot, reset refused: interrupt again
    agent.reset_refusal = None
    agent.resident = []  # as if partly emptied before the retried reset
    await coord.run_once()

    done = step(store)
    assert done.status is StepStatus.DONE
    assert done.snapshot is not None and [m["name"] for m in done.snapshot] == [GEMMA["name"]]
    assert agent.calls.count("interrupt:1") >= 2
    residency_before_reset = agent.calls[: agent.calls.index("reset:1")].count("residency")
    assert residency_before_reset == 1, agent.calls


async def test_an_unobservable_runtime_is_released_without_a_snapshot() -> None:
    """Never recorded as empty: the step says there is no snapshot, and why."""
    store, _ = await entered("n1")
    agent = Agent()
    agent.resident = None
    coord = coordinator(store, {"n1": agent})

    for _ in range(SNAPSHOT_TRIES - 1):
        await coord.run_once()
        assert step(store).phase is StepPhase.INTERRUPTED
    agent_resident_after_restart: list[dict[str, Any]] = []

    async def reset(epoch: int, reset_id: str, *, operator: str) -> dict[str, Any]:
        agent.resident = agent_resident_after_restart
        return {"reset_id": reset_id, "accounting": "resolved"}

    agent.reset = reset  # type: ignore[method-assign]
    await coord.run_once()

    done = step(store)
    assert done.status is StepStatus.DONE
    assert done.snapshot is None
    assert done.snapshot_error is not None and "cannot be restored" in done.snapshot_error


async def test_a_model_resident_after_the_reset_fails_the_node() -> None:
    store, _ = await entered("n1")
    agent = Agent()

    async def reset(epoch: int, reset_id: str, *, operator: str) -> dict[str, Any]:
        return {"reset_id": reset_id, "accounting": "resolved"}  # GEMMA stays

    agent.reset = reset  # type: ignore[method-assign]
    coord = coordinator(store, {"n1": agent})
    for _ in range(3):
        await coord.run_once()

    failed = step(store)
    assert (failed.phase, failed.status) == (StepPhase.RESET, StepStatus.FAILED)
    assert failed.error is not None and GEMMA["name"] in failed.error
    assert status(store) is OperationStatus.FAILED


async def test_senders_that_will_not_stop_keep_the_node_at_pending() -> None:
    store, _ = await entered("n1")
    agent = Agent()
    agent.quiescent = False
    coord = coordinator(store, {"n1": agent})

    await coord.run_once()

    still = step(store)
    assert (still.phase, still.attempts) == (StepPhase.PENDING, 1)
    assert "reset:1" not in agent.calls


async def test_a_node_without_an_agent_fails_at_once() -> None:
    store, _ = await entered("n1")
    await coordinator(store, {}).run_once()
    assert step(store).status is StepStatus.FAILED
    assert status(store) is OperationStatus.FAILED


async def test_an_entry_whose_hold_was_lifted_is_abandoned_untouched() -> None:
    store, _ = await entered("n1")
    await store.maintenance.reopen(changed_by="admin")
    agent = Agent()

    await coordinator(store, {"n1": agent}).run_once()

    assert agent.calls == []
    assert status(store) is OperationStatus.ABANDONED
    assert store.audited[-1][0] is AuditAction.MAINTENANCE_ENTRY_ABANDONED


async def test_a_live_lease_is_respected_and_an_expired_one_taken_over() -> None:
    store, operation = await entered("n1")
    agent = Agent()
    first, second = coordinator(store, {"n1": agent}, "c1"), coordinator(store, {"n1": agent}, "c2")
    await store.claim(owner="c1", lease_s=30)

    assert not await second.run_once(), "c1's lease is live"
    store.now += 31
    assert await second.run_once()
    assert status(store) is OperationStatus.SUCCEEDED

    # c1 wakes up with a stale view: none of its writes land.
    stale = replace(operation.steps[0], phase=StepPhase.RESET)
    assert not await store.advance(stale, owner="c1", phase=StepPhase.VERIFIED)
    assert not await first.run_once()


async def test_a_retried_entry_continues_from_its_recorded_phase() -> None:
    store, operation = await entered("n1")
    agent = Agent()
    agent.reset_refusal = NodeControlError("failed", status=502, refused="restart_failed")
    coord = coordinator(store, {"n1": agent})
    await coord.run_once()
    assert status(store) is OperationStatus.FAILED

    assert await store.retry(operation.id)
    agent.reset_refusal = None
    calls_before = len(agent.calls)
    await coord.run_once()

    assert agent.calls[calls_before:] == ["reset:1", "residency"]
    assert len(set(agent.reset_ids)) == 2, "the failed restart is not reused"
    assert status(store) is OperationStatus.SUCCEEDED
