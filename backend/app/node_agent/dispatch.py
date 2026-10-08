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

from app.node_agent.store import NotOwner, Operation

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
    async def cancel_accepted(self, op_id: str, reason: str) -> Operation | None: ...
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
        self.settled: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()

    def _emit(self, event: dict[str, Any]) -> None:
        if not self._delivery_open:
            return
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            # The caller is not reading. Delivery is given up; the drain goes on.
            self._delivery_open = False
            logger.info("caller of %s stopped reading; delivery abandoned", self.op_id)

    def _close(self) -> None:
        self._delivery_open = False
        with contextlib.suppress(asyncio.QueueFull):
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


class Dispatcher:
    def __init__(
        self,
        store: Store,
        *,
        max_inflight: int = 4,
        max_queued: int = 4,
        host_lock_held: Callable[[], bool] = lambda: True,
    ) -> None:
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

    # -- gate --------------------------------------------------------------

    @property
    def state(self) -> GateState:
        return self._state

    @property
    def admitted(self) -> int:
        return len(self._admitted)

    async def _close(self, state: GateState) -> None:
        async with self._barrier:
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
        await self._close(GateState.DRAINING)
        await self._idle.wait()

    async def reopen(self) -> GateState:
        """Serve again, unless an unknown operation or a lost role forbids it."""
        async with self._barrier:
            if self._state is GateState.LOST:
                return self._state
            self._state = (
                GateState.BLOCKED if await self._store.any_unknown() else GateState.SERVING
            )
            self._gate_changed.set()
            return self._state

    async def wait_idle(self) -> None:
        await self._idle.wait()

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
            if inserted is None:
                found = await self._store.observe(op_id)
                return Existing(found) if found else Refused("conflict", retry_after=1)
            return await self._promote(op_id, relay, provenance or {}, deadline_s)
        finally:
            self._queued -= 1

    async def _promote(
        self, op_id: str, relay: Relay, provenance: dict[str, Any], deadline_s: float
    ) -> Attempt | Refused:
        started = time.monotonic()
        while True:
            remaining = deadline_s - (time.monotonic() - started)
            if remaining <= 0:
                return await self._unsent(op_id, "deadline_before_send")
            if self._state is not GateState.SERVING:
                return await self._unsent(op_id, f"{self._state.value}_before_send")
            self._gate_changed.clear()
            acquire = asyncio.ensure_future(self._slots.acquire())
            changed = asyncio.ensure_future(self._gate_changed.wait())
            done, _ = await asyncio.wait(
                {acquire, changed}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            changed.cancel()
            if acquire in done:
                break
            acquire.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await acquire
            if acquire.done() and not acquire.cancelled():
                self._slots.release()  # acquired as it was being cancelled

        attempt = Attempt(op_id)
        async with self._barrier:
            refusal: str | None = None
            if self._state is not GateState.SERVING:
                refusal = f"{self._state.value}_before_send"
            elif not self._host_lock_held():
                self._state = GateState.LOST
                refusal = "lost_before_send"
            else:
                try:
                    promoted = await self._store.promote(op_id, provenance)
                except NotOwner:
                    self._state = GateState.LOST
                    promoted = False
                if not promoted:
                    refusal = (
                        "lost_before_send" if self._state is GateState.LOST else "node_blocked"
                    )
                else:
                    self._idle.clear()
                    task = asyncio.create_task(self._run(attempt, relay))
                    self._admitted[op_id] = task
        if refusal is not None:
            self._slots.release()
            return await self._unsent(op_id, refusal)
        return attempt

    async def _unsent(self, op_id: str, reason: str) -> Refused:
        try:
            operation = await self._store.cancel_accepted(op_id, reason)
        except NotOwner:
            await self.lose_role("not_owner_at_cancel")
            operation = None
        return Refused(reason, retry_after=_retry_after(self._state), operation=operation)

    async def _run(self, attempt: Attempt, relay: Relay) -> None:
        op_id = attempt.op_id
        outcome: Outcome
        try:
            outcome = await relay(_AttemptSink(self, attempt))
        except Exception as exc:  # noqa: BLE001 - a relay bug is not terminal evidence
            logger.exception("relay for %s raised", op_id)
            outcome = Uncertain(reason=f"relay_error:{type(exc).__name__}")
        try:
            await self._settle(op_id, outcome)
        finally:
            attempt._close()  # noqa: SLF001
            if not attempt.settled.done():
                attempt.settled.set_result(outcome)
            self._slots.release()
            self._admitted.pop(op_id, None)
            if not self._admitted:
                self._idle.set()

    async def _settle(self, op_id: str, outcome: Outcome) -> None:
        try:
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
            else:
                await self.block()
                await self._store.mark_unknown(op_id, outcome.reason, outcome.observed)
        except NotOwner:
            await self.lose_role("not_owner_at_settle")


def _retry_after(state: GateState) -> int | None:
    return {
        GateState.SERVING: 1,
        GateState.DRAINING: 30,
        GateState.BLOCKED: 60,
        GateState.LOST: None,
    }[state]
