"""Admission, the send barrier and attempt settlement (design R3, T2, U1, R5).

Against an in-memory store with the real store's transition rules; the real
store's locking and fencing are covered on PostgreSQL in
`tests/integration/test_node_agent_election.py`.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app.node_agent.dispatch import (
    Attempt,
    Completed,
    Dispatcher,
    Existing,
    GateState,
    NotSent,
    Refused,
    Sink,
    Uncertain,
)
from app.node_agent.store import NotOwner, Operation


class MemoryStore:
    def __init__(self) -> None:
        self.ops: dict[str, Operation] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.observed: dict[str, dict[str, Any]] = {}
        self.owner = True

    def _fence(self) -> None:
        if not self.owner:
            raise NotOwner("superseded")

    async def observe(self, op_id: str) -> Operation | None:
        return self.ops.get(op_id)

    async def any_unknown(self) -> bool:
        return any(o.state == "outcome_unknown" for o in self.ops.values())

    async def insert_accepted(self, op_id: str, kind: str, **kw: Any) -> Operation | None:
        self._fence()
        if op_id in self.ops:
            return None
        op = Operation(
            node_id="n",
            op_id=op_id,
            kind=kind,
            state="accepted",
            origin_generation=1,
            origin_boot_id="b",
            owner_generation=1,
            request_id=kw.get("request_id"),
            payload_hash=kw.get("payload_hash"),
            store_output=kw.get("store_output", False),
            reason=None,
            terminal=None,
            replay_unavailable=False,
        )
        self.ops[op_id] = op
        return op

    def _move(self, op_id: str, frm: str, to: str, **changes: Any) -> bool:
        op = self.ops.get(op_id)
        if op is None or op.state != frm:
            return False
        self.ops[op_id] = replace(op, state=to, **changes)
        return True

    async def promote(self, op_id: str, provenance: dict[str, Any]) -> bool:
        self._fence()
        if await self.any_unknown():
            return False
        return self._move(op_id, "accepted", "running")

    async def cancel_accepted(self, op_id: str, reason: str) -> Operation | None:
        self._fence()
        self._move(op_id, "accepted", "cancelled_unsent", reason=reason)
        return self.ops.get(op_id)

    async def unsent_after_promotion(self, op_id: str, reason: str) -> bool:
        self._fence()
        return self._move(op_id, "running", "cancelled_unsent", reason=reason)

    async def mark_unknown(self, op_id: str, reason: str, observed: dict[str, Any]) -> bool:
        self._fence()
        self.observed[op_id] = observed
        return self._move(op_id, "running", "outcome_unknown", reason=reason)

    async def checkpoint(self, op_id: str, observed: dict[str, Any]) -> None:
        self._fence()
        self.observed[op_id] = observed

    async def finish(
        self,
        op_id: str,
        state: str,
        terminal: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
        replay_unavailable: bool = False,
    ) -> bool:
        self._fence()
        moved = self._move(
            op_id,
            "running",
            state,
            terminal=terminal,
            reason=reason,
            replay_unavailable=replay_unavailable,
        )
        if moved and result is not None:
            self.results[op_id] = result
        return moved


class ScriptedRelay:
    """A relay that records whether it ever 'sent' and waits where told."""

    def __init__(self, outcome: Any = None, *, hold: asyncio.Event | None = None) -> None:
        self.sends = 0
        self.outcome = outcome or Completed(terminal={"eval_count": 2}, result={"content": "ok"})
        self.hold = hold
        self.started = asyncio.Event()

    async def __call__(self, sink: Sink) -> Any:
        self.sends += 1  # the first byte leaves when the relay is entered
        self.started.set()
        sink.emit({"type": "chunk", "content": "o"})
        if self.hold is not None:
            await self.hold.wait()
        sink.emit({"type": "chunk", "content": "k"})
        return self.outcome


async def _drain_events(attempt: Attempt) -> list[dict[str, Any]]:
    return [e async for e in attempt.events()]


async def test_a_duplicate_op_id_only_observes() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    first = ScriptedRelay()
    attempt = await dispatcher.submit("op", "inference", first)
    assert isinstance(attempt, Attempt)
    await attempt.settled

    second = ScriptedRelay()
    again = await dispatcher.submit("op", "inference", second)

    assert isinstance(again, Existing) and again.operation.state == "completed"
    assert second.sends == 0


async def test_a_refusal_at_admission_leaves_no_row() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    await dispatcher.block()

    refused = await dispatcher.submit("op", "inference", ScriptedRelay())

    assert isinstance(refused, Refused) and refused.reason == "node_blocked"
    assert "op" not in store.ops


async def test_a_full_queue_is_an_overload_not_a_wait() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1, max_queued=1)
    hold = asyncio.Event()
    running = await dispatcher.submit("a", "inference", ScriptedRelay(hold=hold))
    assert isinstance(running, Attempt)
    waiting = asyncio.create_task(dispatcher.submit("b", "inference", ScriptedRelay()))
    await asyncio.sleep(0.05)

    overflow = await dispatcher.submit("c", "inference", ScriptedRelay())

    assert isinstance(overflow, Refused) and overflow.reason == "overloaded"
    hold.set()
    assert isinstance(await waiting, Attempt)


async def test_queued_work_frozen_by_a_block_never_sends() -> None:
    """Design T2: X is accepted and waiting for a slot when the node blocks.
    The runtime receives no request from X, and X ends unsent."""
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    hold = asyncio.Event()
    w = await dispatcher.submit("w", "inference", ScriptedRelay(hold=hold))
    assert isinstance(w, Attempt)
    x_relay = ScriptedRelay()
    x = asyncio.create_task(dispatcher.submit("x", "inference", x_relay))
    await asyncio.sleep(0.05)
    assert store.ops["x"].state == "accepted"

    await dispatcher.block()

    refused = await asyncio.wait_for(x, 2)
    assert isinstance(refused, Refused)
    assert x_relay.sends == 0
    assert store.ops["x"].state == "cancelled_unsent"
    hold.set()
    await w.settled


async def test_admitted_work_runs_on_and_holds_drain_while_new_work_is_refused() -> None:
    """Design U1: admitted at the barrier means in flight. A block after
    admission does not stop it; drain waits for its terminal evidence; work
    arriving after the block is refused at the gate."""
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    hold = asyncio.Event()
    x_relay = ScriptedRelay(hold=hold)
    x = await dispatcher.submit("x", "inference", x_relay)
    assert isinstance(x, Attempt)
    await x_relay.started.wait()

    drained = asyncio.create_task(dispatcher.drain())
    await asyncio.sleep(0.05)
    z_relay = ScriptedRelay()
    z = await dispatcher.submit("z", "inference", z_relay)

    assert not drained.done(), "drain waits for admitted work"
    assert isinstance(z, Refused) and z_relay.sends == 0
    hold.set()
    await asyncio.wait_for(drained, 2)
    assert store.ops["x"].state == "completed"


async def test_a_departed_caller_does_not_stop_the_drain() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    hold = asyncio.Event()
    attempt = await dispatcher.submit("x", "inference", ScriptedRelay(hold=hold))
    assert isinstance(attempt, Attempt)

    attempt.abandon()
    hold.set()
    await asyncio.wait_for(attempt.settled, 2)

    assert store.ops["x"].state == "completed"
    assert store.results["x"] == {"content": "ok"}


async def test_a_caller_that_stops_reading_loses_delivery_not_the_attempt() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)

    class Chatty:
        async def __call__(self, sink: Sink) -> Any:
            for i in range(2000):
                sink.emit({"type": "chunk", "content": str(i)})
            return Completed(terminal={"eval_count": 2000}, replay_unavailable=True)

    attempt = await dispatcher.submit("x", "inference", Chatty())
    assert isinstance(attempt, Attempt)
    await asyncio.wait_for(attempt.settled, 2)

    assert store.ops["x"].state == "completed"
    assert store.ops["x"].replay_unavailable


async def test_an_uncertain_outcome_blocks_the_node() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    attempt = await dispatcher.submit(
        "x", "inference", ScriptedRelay(Uncertain("eof_without_done", {"chunks": 1}))
    )
    assert isinstance(attempt, Attempt)
    await attempt.settled

    assert store.ops["x"].state == "outcome_unknown"
    assert store.observed["x"] == {"chunks": 1}
    assert dispatcher.state is GateState.BLOCKED
    later = ScriptedRelay()
    refused = await dispatcher.submit("y", "embedding_batch", later)
    assert isinstance(refused, Refused) and later.sends == 0
    assert await dispatcher.reopen() is GateState.BLOCKED, "still unknown"


async def test_a_connection_refused_before_sending_fails_without_blocking() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    attempt = await dispatcher.submit("x", "inference", ScriptedRelay(NotSent("connect_error")))
    assert isinstance(attempt, Attempt)
    await attempt.settled

    assert store.ops["x"].state == "failed"
    assert store.ops["x"].reason == "not_sent:connect_error"
    assert dispatcher.state is GateState.SERVING


async def test_a_lost_host_lock_admits_nothing_more() -> None:
    store = MemoryStore()
    held = True
    dispatcher = Dispatcher(store, host_lock_held=lambda: held)
    held = False
    relay = ScriptedRelay()

    refused = await dispatcher.submit("x", "inference", relay)

    assert isinstance(refused, Refused) and refused.reason == "lost_before_send"
    assert relay.sends == 0 and dispatcher.state is GateState.LOST
    assert store.ops["x"].state == "cancelled_unsent"
    assert await dispatcher.reopen() is GateState.LOST, "a lost role is never reopened"


async def test_a_superseded_owner_loses_the_role_at_promotion() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    hold = asyncio.Event()
    w = await dispatcher.submit("w", "inference", ScriptedRelay(hold=hold))
    assert isinstance(w, Attempt)
    relay = ScriptedRelay()
    x = asyncio.create_task(dispatcher.submit("x", "inference", relay))
    await asyncio.sleep(0.05)

    store.owner = False
    hold.set()
    refused = await asyncio.wait_for(x, 2)

    assert isinstance(refused, Refused) and relay.sends == 0
    assert dispatcher.state is GateState.LOST


async def test_work_past_its_deadline_before_sending_is_unsent() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    hold = asyncio.Event()
    w = await dispatcher.submit("w", "inference", ScriptedRelay(hold=hold))
    assert isinstance(w, Attempt)
    relay = ScriptedRelay()

    refused = await dispatcher.submit("x", "inference", relay, deadline_s=0.1)

    assert isinstance(refused, Refused) and refused.reason == "deadline_before_send"
    assert relay.sends == 0 and store.ops["x"].state == "cancelled_unsent"
    hold.set()
    await w.settled


async def test_events_reach_a_reading_caller_in_order() -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    attempt = await dispatcher.submit("x", "inference", ScriptedRelay())
    assert isinstance(attempt, Attempt)

    events = await asyncio.wait_for(_drain_events(attempt), 2)

    assert [e["content"] for e in events] == ["o", "k"]


@pytest.mark.parametrize("raises", [RuntimeError("bug"), KeyError("x")])
async def test_a_relay_bug_is_uncertain_not_completion(raises: Exception) -> None:
    store = MemoryStore()
    dispatcher = Dispatcher(store)

    async def broken(sink: Sink) -> Any:
        raise raises

    attempt = await dispatcher.submit("x", "inference", broken)
    assert isinstance(attempt, Attempt)
    await attempt.settled

    assert store.ops["x"].state == "outcome_unknown"
    assert dispatcher.state is GateState.BLOCKED


# -- regressions from the review of #33 --------------------------------------


async def test_resume_cannot_reopen_while_an_unknown_is_still_being_committed() -> None:
    """Finding 1: between the in-process block and the committed unknown, the
    database says nothing is unknown, so `reopen` must not ask it alone."""
    store = MemoryStore()
    committing = asyncio.Event()
    commit_now = asyncio.Event()
    real = store.mark_unknown

    async def slow_mark_unknown(op_id: str, reason: str, observed: dict[str, Any]) -> bool:
        committing.set()
        await commit_now.wait()
        return await real(op_id, reason, observed)

    store.mark_unknown = slow_mark_unknown  # type: ignore[method-assign]
    dispatcher = Dispatcher(store)
    attempt = await dispatcher.submit("u", "inference", ScriptedRelay(Uncertain("eof")))
    assert isinstance(attempt, Attempt)
    await committing.wait()

    assert await dispatcher.reopen() is GateState.BLOCKED
    later = ScriptedRelay()
    assert isinstance(await dispatcher.submit("v", "inference", later), Refused)
    assert later.sends == 0

    commit_now.set()
    await attempt.settled
    assert await dispatcher.reopen() is GateState.BLOCKED, "now committed as unknown"


async def test_a_failing_unknown_commit_is_retried_and_keeps_the_block() -> None:
    """Findings 1 and 6: a database error never turns into another outcome."""
    store = MemoryStore()
    real = store.mark_unknown
    failures = [RuntimeError("pool exhausted"), RuntimeError("connection reset")]

    async def flaky(op_id: str, reason: str, observed: dict[str, Any]) -> bool:
        if failures:
            raise failures.pop(0)
        return await real(op_id, reason, observed)

    store.mark_unknown = flaky  # type: ignore[method-assign]
    dispatcher = Dispatcher(store, settle_retry_s=0.01)
    attempt = await dispatcher.submit("u", "inference", ScriptedRelay(Uncertain("eof")))
    assert isinstance(attempt, Attempt)
    await asyncio.wait_for(attempt.settled, 2)

    assert store.ops["u"].state == "outcome_unknown"
    assert await dispatcher.reopen() is GateState.BLOCKED


async def test_a_failing_completion_commit_is_retried_not_dropped() -> None:
    store = MemoryStore()
    real = store.finish
    failures = [RuntimeError("deadlock detected")]

    async def flaky(op_id: str, state: str, terminal: dict[str, Any], **kw: Any) -> bool:
        if failures:
            raise failures.pop(0)
        return await real(op_id, state, terminal, **kw)

    store.finish = flaky  # type: ignore[method-assign]
    dispatcher = Dispatcher(store, settle_retry_s=0.01)
    attempt = await dispatcher.submit("x", "inference", ScriptedRelay())
    assert isinstance(attempt, Attempt)
    await asyncio.wait_for(attempt.settled, 2)

    assert store.ops["x"].state == "completed"


async def test_a_cancelled_waiter_releases_its_slot_and_its_row() -> None:
    """Finding 2: a handler cancelled while waiting for a slot left a slot
    taken forever and the row accepted."""
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    hold = asyncio.Event()
    w = await dispatcher.submit("w", "inference", ScriptedRelay(hold=hold))
    assert isinstance(w, Attempt)
    waiting = asyncio.create_task(dispatcher.submit("b", "inference", ScriptedRelay()))
    await asyncio.sleep(0.05)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    hold.set()
    await w.settled

    assert store.ops["b"].state == "cancelled_unsent"
    after = await dispatcher.submit("c", "inference", ScriptedRelay())
    assert isinstance(after, Attempt), "the only slot is free again"
    await after.settled


async def test_a_failed_promotion_releases_its_slot_and_settles_the_row() -> None:
    """Finding 3: a database error during promotion leaked the slot."""
    store = MemoryStore()
    real = store.promote
    calls = 0

    async def broken_once(op_id: str, provenance: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            await real(op_id, provenance)  # it committed, then the error
            raise RuntimeError("connection lost after commit")
        return await real(op_id, provenance)

    store.promote = broken_once  # type: ignore[method-assign]
    dispatcher = Dispatcher(store, max_inflight=1)
    relay = ScriptedRelay()

    with pytest.raises(RuntimeError):
        await dispatcher.submit("x", "inference", relay)

    assert relay.sends == 0
    assert store.ops["x"].state == "cancelled_unsent"
    after = await dispatcher.submit("y", "inference", ScriptedRelay())
    assert isinstance(after, Attempt), "the slot came back"
    await after.settled


async def test_a_slow_reader_still_sees_the_stream_end() -> None:
    """Finding 4: with the queue full, the end marker was dropped and the
    reader waited forever, holding the response and the process open."""
    store = MemoryStore()
    dispatcher = Dispatcher(store)

    class Chatty:
        async def __call__(self, sink: Sink) -> Any:
            for i in range(2000):
                sink.emit({"type": "chunk", "content": str(i)})
            return Completed(terminal={"eval_count": 2000})

    attempt = await dispatcher.submit("x", "inference", Chatty())
    assert isinstance(attempt, Attempt)
    await attempt.settled

    events = await asyncio.wait_for(_drain_events(attempt), 2)

    assert attempt.delivery_lost
    assert len(events) < 2000


async def test_a_cancellation_while_queued_is_reported_as_one() -> None:
    """Finding 8: a cancel of queued work came back as `node_blocked`."""
    store = MemoryStore()
    dispatcher = Dispatcher(store, max_inflight=1)
    hold = asyncio.Event()
    w = await dispatcher.submit("w", "inference", ScriptedRelay(hold=hold))
    assert isinstance(w, Attempt)
    queued = asyncio.create_task(dispatcher.submit("q", "inference", ScriptedRelay()))
    await asyncio.sleep(0.05)

    await store.cancel_accepted("q", "cancel_requested")
    hold.set()
    refused = await asyncio.wait_for(queued, 2)

    assert isinstance(refused, Refused) and refused.reason == "cancelled"
    assert dispatcher.state is GateState.SERVING


def test_a_zero_queue_is_refused_at_construction() -> None:
    """Finding 10: a zero queue made every request an overload."""
    with pytest.raises(ValueError):
        Dispatcher(MemoryStore(), max_queued=0)
