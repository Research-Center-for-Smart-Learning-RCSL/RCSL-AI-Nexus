"""The node agent under the maintenance hold (P3 on #61).

What the dispatcher guarantees once the platform closes: promotion refuses
and freezes the gate, a task promoted just before the freeze never sends, an
interrupt cancels the senders that are talking to the runtime and records them
truthfully as unknown, and quiescence is reported apart from settlement.
Against the in-memory store of `test_node_agent_dispatch`, with the hold added;
the database fence itself is covered in
`tests/integration/test_node_agent_maintenance.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.node_agent.dispatch import Attempt, Dispatcher, GateState, Refused, Withheld
from app.node_agent.store import AdmissionClosed
from tests.unit.test_node_agent_dispatch import MemoryStore, ScriptedRelay


class HoldStore(MemoryStore):
    """The in-memory store, with the platform's hold read at promotion."""

    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.epoch = 0
        self.unknown_commits_fail = False

    async def promote(
        self, op_id: str, provenance: dict[str, Any], *, maintenance_epoch: int | None = None
    ) -> bool:
        if maintenance_epoch is not None:
            if not self.closed or self.epoch != maintenance_epoch:
                raise AdmissionClosed(self.epoch)
        elif self.closed:
            raise AdmissionClosed(self.epoch)
        return await super().promote(op_id, provenance)

    async def mark_unknown(self, op_id: str, reason: str, observed: dict[str, Any]) -> bool:
        if self.unknown_commits_fail:
            raise ConnectionError("database away")
        return await super().mark_unknown(op_id, reason, observed)


def close(store: HoldStore, epoch: int = 1) -> None:
    store.closed, store.epoch = True, epoch


async def test_a_promotion_that_reads_the_hold_closed_sends_nothing_and_freezes() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    close(store)
    relay = ScriptedRelay()

    refused = await dispatcher.submit("x", "inference", relay)

    assert isinstance(refused, Refused)
    assert refused.reason == "maintenance_before_send"
    assert relay.sends == 0
    assert store.ops["x"].state == "cancelled_unsent"
    assert dispatcher.state is GateState.MAINTENANCE
    assert dispatcher.frozen_epoch == 1


async def test_a_frozen_gate_survives_reopen_and_thaws_only_when_told() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    await dispatcher.freeze(4)

    assert await dispatcher.reopen() is GateState.MAINTENANCE
    await dispatcher.block()
    assert dispatcher.state is GateState.MAINTENANCE

    assert await dispatcher.thaw() is GateState.SERVING
    assert dispatcher.frozen_epoch is None


async def test_a_task_promoted_just_before_the_freeze_is_withheld_unsent() -> None:
    """The final send barrier: promotion committed, the task not yet run."""
    store = HoldStore()
    dispatcher = Dispatcher(store)
    relay = ScriptedRelay()

    attempt = await dispatcher.submit("x", "inference", relay)
    assert isinstance(attempt, Attempt)
    await dispatcher.freeze(1)  # before the task's first step

    outcome = await asyncio.wait_for(attempt.settled, 1)

    assert isinstance(outcome, Withheld)
    assert relay.sends == 0
    assert store.ops["x"].state == "cancelled_unsent"
    assert store.ops["x"].reason == "maintenance_before_send"


async def test_queued_work_is_cancelled_unsent_when_the_gate_freezes() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    held = ScriptedRelay(hold=asyncio.Event())
    first = await dispatcher.submit("a", "inference", held)
    assert isinstance(first, Attempt)
    await held.started.wait()
    queued_relay = ScriptedRelay()
    queued = asyncio.create_task(dispatcher.submit("b", "inference", queued_relay))
    await asyncio.sleep(0.01)

    await dispatcher.freeze(1)
    refused = await asyncio.wait_for(queued, 1)

    assert isinstance(refused, Refused)
    assert refused.reason == "maintenance_before_send"
    assert queued_relay.sends == 0
    assert store.ops["b"].state == "cancelled_unsent"
    held.hold.set()  # type: ignore[union-attr]
    await asyncio.wait_for(dispatcher.wait_idle(), 1)


async def test_an_interrupt_cancels_the_sender_and_records_it_as_unknown() -> None:
    """Not completion, and not unsent: bytes reached the runtime, so the node
    stays blocked after the hold lifts until a verified reset resolves it."""
    store = HoldStore()
    dispatcher = Dispatcher(store)
    relay = ScriptedRelay(hold=asyncio.Event())
    attempt = await dispatcher.submit("x", "inference", relay)
    assert isinstance(attempt, Attempt)
    await relay.started.wait()
    await dispatcher.freeze(1)

    report = await dispatcher.interrupt(deadline_s=1)

    assert report["interrupted"] == ["x"]
    assert report["quiescent"] is True
    assert report["still_sending"] == []
    await asyncio.wait_for(attempt.settled, 1)
    assert store.ops["x"].state == "outcome_unknown"
    assert store.ops["x"].reason == "maintenance_interrupted"
    assert dispatcher.state is GateState.MAINTENANCE
    await asyncio.wait_for(dispatcher.wait_idle(), 1)

    assert await dispatcher.thaw() is GateState.BLOCKED


async def test_quiescence_is_reported_apart_from_a_settlement_that_cannot_commit() -> None:
    """The database away must not hold up the runtime's stop: the sender is
    gone, the outcome is still being committed, and the report says both."""
    store = HoldStore()
    store.unknown_commits_fail = True
    dispatcher = Dispatcher(store, settle_retry_s=0.01)
    relay = ScriptedRelay(hold=asyncio.Event())
    attempt = await dispatcher.submit("x", "inference", relay)
    assert isinstance(attempt, Attempt)
    await relay.started.wait()
    await dispatcher.freeze(1)

    report = await dispatcher.interrupt(deadline_s=1)

    assert report["quiescent"] is True
    assert report["settling"] == ["x"]
    assert dispatcher.quiescent
    assert dispatcher.admitted == 1

    store.unknown_commits_fail = False
    await asyncio.wait_for(dispatcher.wait_idle(), 2)
    assert store.ops["x"].state == "outcome_unknown"


async def test_an_interrupt_needs_a_frozen_gate() -> None:
    dispatcher = Dispatcher(HoldStore())
    with pytest.raises(RuntimeError, match="frozen"):
        await dispatcher.interrupt(deadline_s=0.1)


async def test_thawing_returns_an_operators_drain_not_service() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    await dispatcher.drain()
    await dispatcher.freeze(1)

    assert await dispatcher.thaw() is GateState.DRAINING
    assert await dispatcher.reopen() is GateState.SERVING


async def test_a_lifecycle_operation_reads_the_hold_too() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    close(store, epoch=2)
    relay = ScriptedRelay()

    refused = await dispatcher.exclusive("load-1", "load", relay)

    assert isinstance(refused, Refused)
    assert refused.reason == "maintenance_before_send"
    assert relay.sends == 0
    assert dispatcher.state is GateState.MAINTENANCE
    assert dispatcher.frozen_epoch == 2


# -- the restore's exception (P5) ---------------------------------------------


async def test_a_restore_load_passes_a_gate_frozen_at_its_epoch_and_keeps_it_frozen() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    close(store, epoch=3)
    await dispatcher.freeze(3)
    relay = ScriptedRelay()

    attempt = await dispatcher.exclusive("restore-1", "load", relay, maintenance_epoch=3)

    assert isinstance(attempt, Attempt)
    await asyncio.wait_for(attempt.settled, 1)
    assert relay.sends == 1
    assert store.ops["restore-1"].state == "completed"
    assert dispatcher.state is GateState.MAINTENANCE


async def test_traffic_stays_refused_while_a_restore_runs() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    close(store, epoch=3)
    await dispatcher.freeze(3)
    held = ScriptedRelay(hold=asyncio.Event())
    attempt = await dispatcher.exclusive("restore-1", "load", held, maintenance_epoch=3)
    assert isinstance(attempt, Attempt)
    await held.started.wait()

    inference = ScriptedRelay()
    refused = await dispatcher.submit("x", "inference", inference)
    second = await dispatcher.exclusive("restore-2", "probe", ScriptedRelay(), maintenance_epoch=3)

    assert isinstance(refused, Refused) and inference.sends == 0
    assert isinstance(second, Refused) and second.reason == "not_frozen_at_epoch"
    held.hold.set()  # type: ignore[union-attr]
    await asyncio.wait_for(attempt.settled, 1)


@pytest.mark.parametrize(("frozen_at", "held_at", "closed"), [(2, 3, True), (3, 3, False)])
async def test_a_restore_for_another_hold_sends_nothing(
    frozen_at: int, held_at: int, closed: bool
) -> None:
    """Frozen for an older entry, or the database hold already lifted: the
    restore's authorisation is the epoch, and it no longer matches."""
    store = HoldStore()
    dispatcher = Dispatcher(store)
    store.closed, store.epoch = closed, held_at
    await dispatcher.freeze(frozen_at)
    relay = ScriptedRelay()

    refused = await dispatcher.exclusive("restore-1", "load", relay, maintenance_epoch=3)

    assert isinstance(refused, Refused)
    assert relay.sends == 0
    assert dispatcher.state is GateState.MAINTENANCE


async def test_an_ordinary_lifecycle_operation_is_still_refused_while_frozen() -> None:
    store = HoldStore()
    dispatcher = Dispatcher(store)
    close(store, epoch=3)
    await dispatcher.freeze(3)
    relay = ScriptedRelay()

    refused = await dispatcher.exclusive("load-1", "load", relay)

    assert isinstance(refused, Refused) and relay.sends == 0


async def test_only_a_load_or_a_probe_may_restore() -> None:
    dispatcher = Dispatcher(HoldStore())
    with pytest.raises(ValueError):
        await dispatcher.exclusive("x", "pull", ScriptedRelay(), maintenance_epoch=1)
