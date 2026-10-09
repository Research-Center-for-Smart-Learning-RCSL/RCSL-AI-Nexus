"""Admission, the send barrier, and the life of one attempt.

The order for every attempt (design R3, T2, U1 on #24):

1. **Observe.** An op id that already exists is returned as it is; a
   duplicate never queues and never sends.
2. **Admit to the queue**, in process: the gate must be serving and the
   queue must have room. A refusal here leaves no row.
3. **Insert `accepted`.** A loser of the insert race only observes.
4. **Wait for a slot**, bounded by the attempt's deadline. Work that waits
   past its deadline, or finds the gate closed, is made `cancelled_unsent`.
5. **Promote and admit, under the barrier.** One hold of the barrier checks
   the gate and the host lock, commits `accepted → running` (which itself
   refuses while any operation is unknown) and marks the task admitted.
   Block, drain and role loss take the same barrier before anything else, so
   nothing is admitted after any of them, and there is no window in which a
   task is promoted but not yet admitted.
6. **Run**, in a task the agent owns. The caller reads events from a bounded
   queue; a slow or departed caller loses delivery, never the drain.
7. **Settle** from the runtime's terminal evidence only.

Admitted work is in flight for every purpose (design U1): drain, exit after a
lost role, and resolution all wait for it to reach terminal evidence.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.node_agent.store import LIFECYCLE_KINDS, NotOwner, Operation

logger = logging.getLogger(__name__)

EVENT_BUFFER = 256
"""Events held for a slow caller before delivery is given up (not the drain)."""


class GateState(enum.Enum):
    SERVING = "serving"
    DRAINING = "draining"
    BLOCKED = "blocked"
    LOST = "lost"


class Store(Protocol):
    async def observe(self, op_id: str) -> Operation | None: ...
    async def any_unknown(self) -> bool: ...
    async def insert_accepted(
        self,
        op_id: str,
        kind: str,
        *,
        request_id: str | None,
        payload_hash: str | None,
        store_output: bool,
    ) -> Operation | None: ...
    async def promote(self, op_id: str, provenance: dict[str, Any]) -> bool: ...
    async def cancel_accepted(self, op_id: str, reason: str, *, kind: str) -> Operation | None: ...
    async def unsent_after_promotion(self, op_id: str, reason: str) -> bool: ...
    async def mark_unknown(self, op_id: str, reason: str, observed: dict[str, Any]) -> bool: ...
    async def checkpoint(self, op_id: str, observed: dict[str, Any]) -> None: ...
    async def finish(
        self,
        op_id: str,
        state: str,
        terminal: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
        replay_unavailable: bool = False,
    ) -> bool: ...


# -- what a runtime relay reports ------------------------------------------


@dataclass(frozen=True, slots=True)
class Completed:
    """The runtime's own terminal evidence: `done` for a stream, the response
    for a call. `terminal` holds its raw totals, never corrected figures."""

    terminal: dict[str, Any]
    result: dict[str, Any] | None = None
    replay_unavailable: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeRefused:
    """The runtime answered with an error: terminal, and nothing ran."""

    terminal: dict[str, Any]
    reason: str


@dataclass(frozen=True, slots=True)
class NotSent:
    """A connection failure established before any request byte was written,
    on the attempt's single transport try (design Q5). Anything weaker is
    `Uncertain`."""

    reason: str


@dataclass(frozen=True, slots=True)
class Uncertain:
    """No terminal evidence after bytes may have been sent: read error, EOF
    without `done`, timeout. Blocks the node (final spec §3)."""

    reason: str
    observed: dict[str, Any] = field(default_factory=dict)


Outcome = Completed | RuntimeRefused | NotSent | Uncertain


class Sink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...
    async def checkpoint(self, observed: dict[str, Any]) -> None: ...


Relay = Callable[[Sink], Awaitable[Outcome]]


# -- what a caller is told -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Refused:
    """Not admitted; `retry_after` is seconds, or None when retrying is futile."""

    reason: str
    retry_after: int | None
    operation: Operation | None = None


@dataclass(frozen=True, slots=True)
class Existing:
    """The op id was already known; this is its state, nothing was run."""

    operation: Operation


class Attempt:
    """A running attempt: its events, then its settled outcome."""

    def __init__(self, op_id: str) -> None:
        self.op_id = op_id
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(EVENT_BUFFER)
        self._delivery_open = True
        self.delivery_lost = False
        """True once any event was not delivered: the caller's view is
        incomplete, whatever the attempt's own outcome (review on #33)."""
        self.settled: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()

    def _emit(self, event: dict[str, Any]) -> None:
        if not self._delivery_open:
            self.delivery_lost = True
            return
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            # The caller is not reading. Delivery is given up; the drain goes on.
            self._delivery_open = False
            self.delivery_lost = True
            logger.info("caller of %s stopped reading; delivery abandoned", self.op_id)

    def _close(self) -> None:
        """End the event stream, always.

        A full queue is emptied first: its events are already undeliverable in
        order, and an end marker that could not be queued would leave the
        reader waiting forever, holding the response open and the process,
        and with it the host lock, alive (review on #33).
        """
        self._delivery_open = False
        if self._events.full():
            while not self._events.empty():
                self._events.get_nowait()
            self.delivery_lost = True
        self._events.put_nowait(None)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    def abandon(self) -> None:
        """The caller went away. Nothing stops: only delivery does."""
        self._delivery_open = False


class _AttemptSink:
    def __init__(self, dispatcher: Dispatcher, attempt: Attempt) -> None:
        self._dispatcher = dispatcher
        self._attempt = attempt

    def emit(self, event: dict[str, Any]) -> None:
        self._attempt._emit(event)  # noqa: SLF001

    async def checkpoint(self, observed: dict[str, Any]) -> None:
        try:
            await self._dispatcher._store.checkpoint(self._attempt.op_id, observed)  # noqa: SLF001
        except NotOwner:
            await self._dispatcher.lose_role("not_owner_at_checkpoint")
        except Exception:  # noqa: BLE001 - a missed checkpoint loses only an observation
            logger.warning("checkpoint of %s failed", self._attempt.op_id, exc_info=True)


SETTLE_RETRY_CAP_S = 5.0


class Dispatcher:
    def __init__(
        self,
        store: Store,
        *,
        max_inflight: int = 4,
        max_queued: int = 4,
        host_lock_held: Callable[[], bool] = lambda: True,
        settle_retry_s: float = 0.2,
    ) -> None:
        if max_inflight < 1 or max_queued < 1:
            raise ValueError("max_inflight and max_queued must be at least 1")
        self._store = store
        self._barrier = asyncio.Lock()
        self._state = GateState.SERVING
        self._slots = asyncio.Semaphore(max_inflight)
        self._max_queued = max_queued
        self._queued = 0
        self._admitted: dict[str, asyncio.Task[None]] = {}
        self._idle = asyncio.Event()
        self._idle.set()
        self._gate_changed = asyncio.Event()
        self._host_lock_held = host_lock_held
        self._settle_retry_s = settle_retry_s
        self._exclusive: str | None = None
        """The lifecycle operation holding the node, if any (`exclusive`)."""
        self._held_by_operator = False
        """An operator's drain, which a lifecycle operation ending must not undo."""
        self._uncommitted_unknown: set[str] = set()
        """Operations this process knows are uncertain but has not yet
        committed as `outcome_unknown`. The database cannot see them, so
        `reopen` must (review on #33: a resume between the in-process block
        and the commit reopened the gate)."""

    # -- gate --------------------------------------------------------------

    @property
    def state(self) -> GateState:
        return self._state

    @property
    def admitted(self) -> int:
        return len(self._admitted)

    async def _close(self, state: GateState) -> None:
        async with self._barrier:
            self._close_locked(state)

    def _close_locked(self, state: GateState) -> None:
        if self._state is GateState.LOST:
            return
        if state is GateState.DRAINING and self._state is GateState.BLOCKED:
            return  # a block outranks a drain; resuming will re-check
        self._state = state
        self._gate_changed.set()

    async def block(self) -> None:
        """Close the gate before an unknown is committed (design T2)."""
        await self._close(GateState.BLOCKED)

    async def lose_role(self, reason: str) -> None:
        logger.error("node role lost (%s); no further admission", reason)
        await self._close(GateState.LOST)

    async def drain(self) -> None:
        """Admit nothing more and wait for admitted work to reach terminal
        evidence. Queued `accepted` work is cancelled as it reaches promotion."""
        async with self._barrier:
            self._held_by_operator = True
            self._close_locked(GateState.DRAINING)
        await self._idle.wait()

    async def reopen(self) -> GateState:
        """Serve again, unless an unknown operation or a lost role forbids it.

        Unknown means committed **or** known here and not yet committed.
        """
        async with self._barrier:
            self._held_by_operator = False
            return await self._reopen_locked()

    async def _reopen_locked(self) -> GateState:
        if self._state is GateState.LOST or self._exclusive is not None:
            return self._state
        blocked = bool(self._uncommitted_unknown) or await self._store.any_unknown()
        self._state = GateState.BLOCKED if blocked else GateState.SERVING
        self._gate_changed.set()
        return self._state

    def holds(self, op_id: str) -> bool:
        """Whether this process still has a task for the operation."""
        return op_id in self._admitted

    async def wait_idle(self) -> None:
        await self._idle.wait()

    # -- lifecycle ---------------------------------------------------------

    async def exclusive(
        self,
        op_id: str,
        kind: str,
        relay: Relay,
        *,
        provenance: dict[str, Any] | None = None,
        after: Callable[[Outcome], Awaitable[None]] | None = None,
    ) -> Attempt | Existing | Refused:
        """Run a lifecycle operation with the node to itself (PR4b, design S5).

        Admission closes first, as a drain: queued work is cancelled unsent as
        it reaches promotion, and admitted work is waited for to terminal
        evidence. Only then is the operation promoted, under the same barrier
        and the same refusal while anything is unknown. `after` runs once the
        outcome is committed and before the node serves again, so a pull's new
        pin is in place before anything is dispatched against it. The node
        reopens when the operation ends, unless an operator's drain, a block
        or a lost role says otherwise.

        Unlike inference, an operation whose outcome is uncertain fails rather
        than blocks: it changes what the runtime holds, which the heartbeat
        observes again, and a pull that may have rewritten a tag is caught by
        the weights pin (final spec §3 blocks on inference, summary and
        embedding).
        """
        if kind not in LIFECYCLE_KINDS:
            raise ValueError(f"{kind} is not a lifecycle operation")
        existing = await self._store.observe(op_id)
        if existing is not None:
            return Existing(existing)
        async with self._barrier:
            if self._state is not GateState.SERVING:
                return Refused(f"node_{self._state.value}", retry_after=_retry_after(self._state))
            self._exclusive = op_id
            self._close_locked(GateState.DRAINING)
        handed_off = False
        try:
            try:
                inserted = await self._store.insert_accepted(
                    op_id, kind, request_id=None, payload_hash=None, store_output=False
                )
            except NotOwner:
                await self.lose_role("not_owner_at_insert")
                return Refused("node_lost", retry_after=None)
            if inserted is None:
                found = await self._store.observe(op_id)
                return Existing(found) if found else Refused("conflict", retry_after=1)
            try:
                await self._idle.wait()
                await self._slots.acquire()
            except asyncio.CancelledError:
                await _shielded(self._unsent(op_id, kind, "cancelled_before_send"))
                raise
            attempt = Attempt(op_id)
            refusal: str | None = None
            try:
                async with self._barrier:
                    # Re-read: a block or a lost role may have replaced the drain
                    # while admitted work finished (mypy narrowed it above).
                    state: GateState = self._state
                    if state is not GateState.DRAINING:
                        refusal = f"{state.value}_before_send"
                    elif not self._host_lock_held():
                        self._state = GateState.LOST
                        refusal = "lost_before_send"
                    else:
                        try:
                            promoted = await self._store.promote(op_id, provenance or {})
                        except NotOwner:
                            self._state = GateState.LOST
                            promoted = False
                        if promoted:
                            self._idle.clear()
                            self._admitted[op_id] = asyncio.create_task(
                                self._run(attempt, relay, kind=kind, after=after)
                            )
                            handed_off = True
                        else:
                            refusal = (
                                "lost_before_send"
                                if self._state is GateState.LOST
                                else "node_blocked"
                            )
            except BaseException:
                if not handed_off:
                    self._slots.release()
                    await _shielded(self._unsent_after_failed_promotion(op_id, kind))
                raise
            if handed_off:
                return attempt
            self._slots.release()
            return await self._unsent(op_id, kind, refusal or "not_promoted")
        finally:
            if not handed_off:
                await self._end_exclusive(op_id)

    async def _end_exclusive(self, op_id: str) -> None:
        async with self._barrier:
            if self._exclusive != op_id:
                return
            self._exclusive = None
            if self._state is GateState.DRAINING and not self._held_by_operator:
                await self._reopen_locked()

    # -- one attempt -------------------------------------------------------

    async def submit(
        self,
        op_id: str,
        kind: str,
        relay: Relay,
        *,
        request_id: str | None = None,
        payload_hash: str | None = None,
        store_output: bool = False,
        provenance: dict[str, Any] | None = None,
        deadline_s: float = 30.0,
    ) -> Attempt | Existing | Refused:
        existing = await self._store.observe(op_id)
        if existing is not None:
            return Existing(existing)

        async with self._barrier:
            if self._state is not GateState.SERVING:
                return Refused(f"node_{self._state.value}", retry_after=_retry_after(self._state))
            if self._queued >= self._max_queued:
                return Refused("overloaded", retry_after=2)
            self._queued += 1
        try:
            try:
                inserted = await self._store.insert_accepted(
                    op_id,
                    kind,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    store_output=store_output,
                )
            except NotOwner:
                await self.lose_role("not_owner_at_insert")
                return Refused("node_lost", retry_after=None)
            except asyncio.CancelledError:
                # The insert may or may not have committed. A tombstone or a
                # cancellation of the accepted row covers both, and a late
                # duplicate then only observes it.
                await _shielded(self._unsent(op_id, kind, "cancelled_before_send"))
                raise
            if inserted is None:
                found = await self._store.observe(op_id)
                return Existing(found) if found else Refused("conflict", retry_after=1)
            return await self._promote(op_id, kind, relay, provenance or {}, deadline_s)
        finally:
            self._queued -= 1

    async def _wait_for_slot(self, op_id: str, deadline_s: float) -> str | None:
        """A held slot (None), or the reason the attempt will not be sent."""
        started = time.monotonic()
        while True:
            remaining = deadline_s - (time.monotonic() - started)
            if remaining <= 0:
                return "deadline_before_send"
            if self._state is not GateState.SERVING:
                return f"{self._state.value}_before_send"
            self._gate_changed.clear()
            acquire = asyncio.ensure_future(self._slots.acquire())
            changed = asyncio.ensure_future(self._gate_changed.wait())
            acquired = False
            try:
                done, _ = await asyncio.wait(
                    {acquire, changed}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                acquired = acquire in done
            finally:
                # On every exit, this task's own cancellation included: an
                # acquire left running would take a slot nobody releases
                # (review on #33). Let it settle, and give back what it took.
                changed.cancel()
                if not acquired:
                    if not acquire.done():
                        acquire.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.wait({acquire})
                    if acquire.done() and not acquire.cancelled():
                        self._slots.release()
            if acquired:
                return None

    async def _promote(
        self,
        op_id: str,
        kind: str,
        relay: Relay,
        provenance: dict[str, Any],
        deadline_s: float,
    ) -> Attempt | Refused:
        try:
            waited = await self._wait_for_slot(op_id, deadline_s)
        except asyncio.CancelledError:
            await _shielded(self._unsent(op_id, kind, "cancelled_before_send"))
            raise
        if waited is not None:
            return await self._unsent(op_id, kind, waited)

        attempt = Attempt(op_id)
        created = False
        try:
            async with self._barrier:
                if self._state is not GateState.SERVING:
                    refusal: str | None = f"{self._state.value}_before_send"
                elif not self._host_lock_held():
                    self._state = GateState.LOST
                    refusal = "lost_before_send"
                else:
                    try:
                        promoted = await self._store.promote(op_id, provenance)
                    except NotOwner:
                        self._state = GateState.LOST
                        promoted = False
                    if promoted:
                        self._idle.clear()
                        self._admitted[op_id] = asyncio.create_task(
                            self._run(attempt, relay, kind=kind)
                        )
                        created = True
                        refusal = None
                    elif self._state is GateState.LOST:
                        refusal = "lost_before_send"
                    else:
                        refusal = "not_promoted"
        except BaseException:
            # The promotion's own outcome is unknown here (a database error or
            # this task's cancellation), but no task exists, so nothing was
            # sent. Settle the row as unsent whichever state it reached.
            if not created:
                self._slots.release()
                await _shielded(self._unsent_after_failed_promotion(op_id, kind))
            raise
        if created:
            return attempt
        self._slots.release()
        if refusal == "not_promoted":
            # Blocked by an unknown, or cancelled while queued: say which.
            current = await self._store.observe(op_id)
            if current is not None and current.state == "cancelled_unsent":
                return Refused("cancelled", retry_after=None, operation=current)
            refusal = "node_blocked"
        return await self._unsent(op_id, kind, refusal or "not_promoted")

    async def _unsent_after_failed_promotion(self, op_id: str, kind: str) -> None:
        try:
            current = await self._store.observe(op_id)
            if current is None or current.state == "accepted":
                await self._store.cancel_accepted(op_id, "promotion_failed", kind=kind)
            elif current.state == "running":
                await self._store.unsent_after_promotion(op_id, "promotion_failed")
        except Exception:  # noqa: BLE001 - the row's state is now unknown to us
            logger.exception("could not settle %s after a failed promotion; blocking", op_id)
            async with self._barrier:
                self._uncommitted_unknown.add(op_id)
                self._close_locked(GateState.BLOCKED)

    async def _unsent(self, op_id: str, kind: str, reason: str) -> Refused:
        try:
            operation = await self._store.cancel_accepted(op_id, reason, kind=kind)
        except NotOwner:
            await self.lose_role("not_owner_at_cancel")
            operation = None
        return Refused(reason, retry_after=_retry_after(self._state), operation=operation)

    async def _run(
        self,
        attempt: Attempt,
        relay: Relay,
        *,
        kind: str,
        after: Callable[[Outcome], Awaitable[None]] | None = None,
    ) -> None:
        op_id = attempt.op_id
        outcome: Outcome
        cancelled: asyncio.CancelledError | None = None
        try:
            outcome = await relay(_AttemptSink(self, attempt))
        except asyncio.CancelledError as exc:
            # Cancelled after promotion, so bytes may have gone out: unknown,
            # and settled like any other outcome before the cancellation goes
            # on, or the slot, the stream and drain would wait for ever
            # (review of #33's branch).
            outcome = Uncertain(reason="relay_cancelled")
            cancelled = exc
        except Exception as exc:  # noqa: BLE001 - a relay bug is not terminal evidence
            logger.exception("relay for %s raised", op_id)
            outcome = Uncertain(reason=f"relay_error:{type(exc).__name__}")
        lifecycle = kind in LIFECYCLE_KINDS
        try:
            await self._settle(op_id, outcome, blocking=not lifecycle)
            if after is not None:
                try:
                    await after(outcome)
                except Exception:  # noqa: BLE001 - the outcome is committed already
                    logger.exception("the follow-up of %s failed", op_id)
        finally:
            attempt._close()  # noqa: SLF001
            if not attempt.settled.done():
                attempt.settled.set_result(outcome)
            self._slots.release()
            self._admitted.pop(op_id, None)
            if not self._admitted:
                self._idle.set()
            if lifecycle:
                await _shielded(self._end_exclusive(op_id))
        if cancelled is not None:
            raise cancelled

    async def _settle(self, op_id: str, outcome: Outcome, *, blocking: bool = True) -> None:
        """Commit the outcome, retrying until it is committed or the role is lost.

        A database error never turns into a different outcome (review on
        #33): an uncertain attempt stays blocking in process until its
        unknown is committed, and the task, with its slot, is held until the
        commit, so drain and exit wait for it too.
        """
        if isinstance(outcome, Uncertain) and blocking:
            async with self._barrier:
                self._uncommitted_unknown.add(op_id)
                self._close_locked(GateState.BLOCKED)

        async def commit() -> None:
            if isinstance(outcome, Completed):
                await self._store.finish(
                    op_id,
                    "completed",
                    outcome.terminal,
                    result=outcome.result,
                    replay_unavailable=outcome.replay_unavailable,
                )
            elif isinstance(outcome, RuntimeRefused):
                await self._store.finish(op_id, "failed", outcome.terminal, reason=outcome.reason)
            elif isinstance(outcome, NotSent):
                await self._store.finish(op_id, "failed", {}, reason=f"not_sent:{outcome.reason}")
            elif not blocking:
                await self._store.finish(
                    op_id, "failed", outcome.observed, reason=f"uncertain:{outcome.reason}"
                )
            else:
                await self._store.mark_unknown(op_id, outcome.reason, outcome.observed)

        delay = self._settle_retry_s
        while True:
            try:
                await commit()
            except NotOwner:
                await self.lose_role("not_owner_at_settle")
                return  # the gate stays closed for good; the row is takeover's
            except Exception:  # noqa: BLE001 - retried, never reinterpreted
                logger.exception("could not commit the outcome of %s; retrying", op_id)
                await asyncio.sleep(delay)
                delay = min(delay * 2, SETTLE_RETRY_CAP_S)
                continue
            break
        if isinstance(outcome, Uncertain) and blocking:
            self._uncommitted_unknown.discard(op_id)


async def _shielded(work: Awaitable[Any]) -> None:
    """Run cleanup to completion even though the caller is being cancelled."""
    with contextlib.suppress(Exception):
        await asyncio.shield(asyncio.ensure_future(work))


def _retry_after(state: GateState) -> int | None:
    return {
        GateState.SERVING: 1,
        GateState.DRAINING: 30,
        GateState.BLOCKED: 60,
        GateState.LOST: None,
    }[state]
