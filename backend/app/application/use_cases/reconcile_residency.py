"""Restore desired residency after a runtime restart (#49 §2, fixes #23).

After Ollama restarts it holds nothing, the heartbeat records every model as
`downloaded`, and routing, strict on fresh observed residency, refuses every
capability. Nothing used to reconcile the intent with that observation. This
does, within bounds:

- It acts only on **two consecutive positive `downloaded` observations** of a
  model whose `desired_resident` is set. A failed, missing or stale probe is
  not evidence.
- It restores **largest first** and, after each load, re-observes **the whole
  node** through the runtime, because a load can evict a sibling. Desired
  models still not resident are re-queued, for at most two repair rounds per
  pass; then the node backs off, `30 s × 2^n` up to 15 minutes. After
  `GIVE_UP_AFTER_WASTED_PASSES` such failures that each loaded weights, with
  the intent unchanged, it **gives up** on the node and logs an error, until
  the intent changes or the desired set is observed resident.
- Every load is `ManageModels.restore`: the operator's checks, memory budget,
  state transitions and audit, and through the node agent's exclusive
  lifecycle path, which keeps production load options (registered `num_ctx`,
  the deployment's `keep_alive`, nothing else).
- It **never dispatches while the node is blocked** by an `outcome_unknown`
  operation, while a lifecycle operation is already in flight on the node,
  while another reconciler holds the node, or while suspended. Elapsed time is
  never a reason to proceed.
- Intent follows the latest value. It is re-read before every load and again
  after it returns; weights whose intent was withdrawn meanwhile are unloaded.

Where it runs. The final spec places reconciliation in the node agent; it runs
here, in the tailnet admin beside the heartbeat, because the memory budget and
the registry's lifecycle live in the control plane. Every load still reaches the
runtime only through the agent, which serialises it with operator lifecycle work.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.domain.entities.model import Model, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.services.residency_reconciliation import (
    GIVE_UP_AFTER_WASTED_PASSES,
    MAX_REPAIR_ROUNDS,
    REQUIRED_ABSENT_OBSERVATIONS,
    TRANSIENT_STATES,
    AbsenceEvidence,
    backoff_seconds,
    observed_absent,
    observed_resident,
    restorable,
    restore_order,
)

logger = logging.getLogger(__name__)


class ReconcilerStatePort(Protocol):
    """Committed control-plane state, each read in its own short transaction."""

    async def nodes(self) -> list[Node]: ...
    async def models_on(self, node_id: str) -> list[Model]: ...

    async def node_blocked(self, node_id: str) -> bool:
        """Any `outcome_unknown` operation on the node. Read before every load."""
        ...

    async def now(self) -> datetime:
        """The database clock, which stamps the observations."""
        ...


class ResidencyObserverPort(Protocol):
    async def observe(self, node: Node) -> None:
        """Probe the node's runtime once and write every model's observation,
        as the heartbeat does. Read-only towards the runtime."""
        ...


class ModelRestorerPort(Protocol):
    """`ManageModels.restore` and `release`, one transaction each."""

    async def restore(self, model_id: str) -> Model: ...
    async def release(self, model_id: str) -> Model: ...


class NodeSerialisationPort(Protocol):
    def hold(self, node_id: str) -> AbstractAsyncContextManager[bool]:
        """Exclusive across processes for one pass; yields False when another
        holder has the node, and the pass is then skipped, never waited for."""
        ...


Suspension = Callable[[], Awaitable[bool]]
"""True while reconciliation must not act. The hook a maintenance mode (#61)
will supply; until then nothing suspends it but the flag."""


async def _never_suspended() -> bool:
    return False


class PassResult(enum.StrEnum):
    IDLE = "idle"
    """Nothing desired is due: resident, or not yet twice observed absent."""
    RESTORED = "restored"
    """The whole desired set was observed resident after this pass's loads."""
    FAILED = "failed"
    """A load failed, evidence went missing, or repair rounds ran out; the
    node now backs off."""
    BACKING_OFF = "backing_off"
    BLOCKED = "blocked"
    """An uncertain operation blocks the node. Not a failure: no backoff."""
    BUSY = "busy"
    """A lifecycle operation is in flight, or another reconciler holds the node."""
    UNHEALTHY = "unhealthy"
    SUSPENDED = "suspended"
    GAVE_UP = "gave_up"
    """Restores kept failing after loading weights, for the same intent. The
    node is left alone until its intent changes or the set is resident."""


@dataclass(frozen=True)
class PassOutcome:
    node_id: str
    result: PassResult
    restored: tuple[str, ...] = ()
    released: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class _Backoff:
    failures: int = 0
    until: datetime | None = None
    wasted: int = 0
    """Consecutive failed passes that loaded weights before failing."""
    gave_up: bool = False


@dataclass
class _Progress:
    restored: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)


class ReconcileResidency:
    def __init__(
        self,
        state: ReconcilerStatePort,
        observer: ResidencyObserverPort,
        restorer: ModelRestorerPort,
        serialisation: NodeSerialisationPort,
        *,
        enabled: bool,
        suspended: Suspension = _never_suspended,
    ) -> None:
        self._state = state
        self._observer = observer
        self._restorer = restorer
        self._serialisation = serialisation
        self._enabled = enabled
        self._suspended = suspended
        # Process-local on purpose: a restarted admin starts counting again,
        # which can only delay a restore, never hasten one.
        self._evidence = AbsenceEvidence()
        self._backoff: dict[str, _Backoff] = {}
        # Each node's desired set and versions as last seen. A change resets
        # the backoff and any give-up: someone has asked for something new.
        self._intents: dict[str, frozenset[tuple[str, int]]] = {}

    async def run_once(self) -> list[PassOutcome]:
        """One pass over every node. Never raises for one node's failure."""
        if not self._enabled:
            return []
        outcomes: list[PassOutcome] = []
        for node in await self._state.nodes():
            if RuntimeKind.OLLAMA not in node.runtimes:
                continue
            try:
                outcome = await self._reconcile(node)
            except Exception as exc:  # noqa: BLE001 - one node must not stop the others
                logger.exception("residency reconciliation of node %s failed", node.id)
                outcome = await self._fail(node.id, f"error:{type(exc).__name__}", _Progress())
            # A give-up is logged once, loudly, when it happens.
            if outcome.result not in (PassResult.IDLE, PassResult.GAVE_UP):
                logger.info(
                    "residency pass node=%s result=%s restored=%s released=%s reason=%s",
                    outcome.node_id,
                    outcome.result.value,
                    ",".join(outcome.restored) or "-",
                    ",".join(outcome.released) or "-",
                    outcome.reason or "-",
                )
            outcomes.append(outcome)
        return outcomes

    async def _reconcile(self, node: Node) -> PassOutcome:
        if await self._suspended():
            return PassOutcome(node.id, PassResult.SUSPENDED)
        now = await self._state.now()
        models = [m for m in await self._state.models_on(node.id) if _reconcilable(m)]
        desired = [m for m in models if m.desired_resident]
        intent = frozenset((m.id, m.desired_version) for m in desired)
        previous = self._intents.get(node.id)
        self._intents[node.id] = intent
        if previous is not None and previous != intent:
            self._backoff.pop(node.id, None)
        if all(observed_resident(m, now) for m in desired if restorable(m, now)):
            self._backoff.pop(node.id, None)
        backoff = self._backoff.get(node.id)
        if backoff is not None and backoff.gave_up:
            return PassOutcome(node.id, PassResult.GAVE_UP)
        if backoff is not None and backoff.until is not None and now < backoff.until:
            return PassOutcome(node.id, PassResult.BACKING_OFF)

        for model in models:
            if not model.desired_resident:
                self._evidence.forget(model.id)
        due = [
            m
            for m in desired
            if self._evidence.record(m, now) >= REQUIRED_ABSENT_OBSERVATIONS
            and m.state not in TRANSIENT_STATES
        ]
        if not due:
            return PassOutcome(node.id, PassResult.IDLE)
        if node.status is not NodeStatus.ONLINE:
            return PassOutcome(node.id, PassResult.UNHEALTHY)
        if any(m.state in TRANSIENT_STATES for m in models):
            return PassOutcome(node.id, PassResult.BUSY, reason="lifecycle_in_flight")
        if await self._state.node_blocked(node.id):
            return PassOutcome(node.id, PassResult.BLOCKED)

        async with self._serialisation.hold(node.id) as held:
            if not held:
                return PassOutcome(node.id, PassResult.BUSY, reason="held_elsewhere")
            return await self._restore(node, restore_order(due))

    async def _restore(self, node: Node, queue: list[Model]) -> PassOutcome:
        progress = _Progress()
        for _ in range(1 + MAX_REPAIR_ROUNDS):
            for target in queue:
                stopped = await self._restore_one(node, target.id, progress)
                if stopped is not None:
                    return stopped
            # The whole node, not just what was loaded: a load can evict a
            # sibling restored earlier in this pass, or one that was resident.
            now = await self._state.now()
            missing = [
                m
                for m in await self._state.models_on(node.id)
                if restorable(m, now) and not observed_resident(m, now)
            ]
            if not missing:
                self._backoff.pop(node.id, None)
                return PassOutcome(
                    node.id,
                    PassResult.RESTORED,
                    tuple(progress.restored),
                    tuple(progress.released),
                )
            queue = restore_order(missing)
        return await self._fail(node.id, "repair_rounds_exhausted", progress)

    async def _restore_one(
        self, node: Node, model_id: str, progress: _Progress
    ) -> PassOutcome | None:
        """Load one model if it is still wanted and still absent. A returned
        outcome ends the pass; None means go on to the next model."""
        if await self._suspended():
            return _ended(node.id, PassResult.SUSPENDED, progress)
        # Re-checked before every load, never cached from the start of the pass.
        if await self._state.node_blocked(node.id):
            return _ended(node.id, PassResult.BLOCKED, progress)
        now = await self._state.now()
        current = _find(await self._state.models_on(node.id), model_id)
        if current is None or not current.desired_resident:
            return None
        if observed_resident(current, now):
            return None
        if current.state in TRANSIENT_STATES:
            return _ended(node.id, PassResult.BUSY, progress, "lifecycle_in_flight")
        if not observed_absent(current, now):
            # Unknown is not absence: never load on a missing observation.
            return await self._fail(node.id, "residency_unobserved", progress)
        try:
            await self._restorer.restore(current.id)
        except Exception as exc:  # noqa: BLE001 - insufficient memory, refusal, outage
            logger.warning("restoring %s failed: %s", current.alias, exc)
            return await self._fail(node.id, f"load_failed:{type(exc).__name__}", progress)
        progress.restored.append(current.alias)

        after = _find(await self._state.models_on(node.id), model_id)
        if after is None or not after.desired_resident:
            # Withdrawn while the load was in flight: the fresh weights go.
            try:
                await self._restorer.release(model_id)
                progress.released.append(current.alias)
            except Exception as exc:  # noqa: BLE001
                logger.warning("releasing withdrawn %s failed: %s", current.alias, exc)
                return await self._fail(node.id, f"release_failed:{type(exc).__name__}", progress)
        await self._observer.observe(node)
        return None

    async def _fail(self, node_id: str, reason: str, progress: _Progress) -> PassOutcome:
        backoff = self._backoff.setdefault(node_id, _Backoff())
        backoff.failures += 1
        now = await self._state.now()
        backoff.until = now + timedelta(seconds=backoff_seconds(backoff.failures))
        # Only a pass that loaded weights and still failed counts towards
        # giving up: that is the cost worth stopping. A refusal or an outage
        # loads nothing, and backing off is enough for it.
        if progress.restored:
            backoff.wasted += 1
        if backoff.wasted >= GIVE_UP_AFTER_WASTED_PASSES and not backoff.gave_up:
            backoff.gave_up = True
            logger.error(
                "residency reconciler gave up on node %s after %d failed restores of the "
                "same desired set (last: %s); it will not reload this node until its "
                "residency intent changes or the desired set is observed resident",
                node_id,
                backoff.wasted,
                reason,
            )
        # After a failure, fresh evidence is required again: the load itself
        # cleared and rewrote observations, so older answers no longer chain.
        for model in await self._state.models_on(node_id):
            self._evidence.forget(model.id)
        return PassOutcome(
            node_id,
            PassResult.FAILED,
            tuple(progress.restored),
            tuple(progress.released),
            reason,
        )


def _reconcilable(model: Model) -> bool:
    # MLX cannot report residency: no automatic reload (final spec §3).
    return model.runtime is RuntimeKind.OLLAMA


def _find(models: list[Model], model_id: str) -> Model | None:
    return next((m for m in models if m.id == model_id), None)


def _ended(
    node_id: str, result: PassResult, progress: _Progress, reason: str | None = None
) -> PassOutcome:
    return PassOutcome(node_id, result, tuple(progress.restored), tuple(progress.released), reason)
