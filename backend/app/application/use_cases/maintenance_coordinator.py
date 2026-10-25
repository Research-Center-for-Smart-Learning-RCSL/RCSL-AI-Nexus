"""Carrying a maintenance entry out on every node (P4 on #61).

An administrator's entry closes access and records an operation with one step
per node (`manage_maintenance.py`). This takes the operation from there: for
each node, interrupt, snapshot, reset and verify, as `maintenance_operation.py`
describes, writing each result before the next call. It runs in the tailnet
admin, the process that already owns the control plane's background writers.

**What it never does.**

- Hold a database transaction across a call to a node. Every read and write
  here is its own short transaction through `CoordinatorStore`.
- Treat a lease expiry, a timeout or an unanswered node as evidence. A step
  that cannot be confirmed is retried from what was recorded, and fails after
  `max_attempts`; the platform stays closed either way.
- Reopen anything. Lifting the hold is an administrator's act, and restoring
  the models before it is P5's.
- Replace a snapshot. The first one taken is the set P5 restores.

A pass claims the oldest running operation, advances every running step as
far as it will go, and closes the operation once no step is left running:
`succeeded` when every node verified empty, `failed` otherwise. Steps advance
concurrently, one task per node, so one slow node does not hold up the rest.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol

from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance import MaintenanceState
from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    NodeStep,
    OperationKind,
    OperationStatus,
    StepPhase,
    StepStatus,
    resident_matches,
    restore_order,
    snapshot_of,
)
from app.domain.ports.node_control_port import NodeControlError, NodeControlPort
from app.domain.services.residency_reconciliation import MAX_REPAIR_ROUNDS

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
"""Per phase, across passes. A pass is a couple of seconds apart, so this is
long enough for an agent or a runtime that is restarting, and short enough
that a node which will not answer is reported rather than waited on."""

SNAPSHOT_TRIES = 3
"""How many times an unobservable runtime is asked before the entry carries on
without a snapshot. Releasing the runtime is the entry's purpose and must not
wait on it; the step records why there is no snapshot, and P5 refuses to
restore that node automatically."""

COORDINATOR = "maintenance coordinator"

FINAL_REFUSALS = frozenset({"restart_failed", "repairs_exhausted", "unexpected_resident"})
"""Refusals another attempt cannot change: they wait for an administrator."""


class CoordinatorStore(Protocol):
    """Each method its own transaction (`infrastructure/maintenance_coordinator.py`)."""

    async def hold(self) -> MaintenanceState: ...

    async def claim(self, *, owner: str, lease_s: float) -> MaintenanceOperation | None: ...

    async def renew(self, operation_id: str, *, owner: str, lease_s: float) -> bool: ...

    async def get(self, operation_id: str) -> MaintenanceOperation | None: ...

    async def advance(
        self, step: NodeStep, *, owner: str, phase: StepPhase, **values: Any
    ) -> bool: ...

    async def set_reset_id(self, step: NodeStep, *, owner: str, reset_id: str) -> bool: ...

    async def attempt_failed(
        self,
        step: NodeStep,
        *,
        owner: str,
        error: str,
        max_attempts: int,
        clear_reset_id: bool = False,
        final: bool = False,
    ) -> NodeStep | None: ...

    async def finish(
        self, operation_id: str, *, owner: str, status: OperationStatus, error: str | None = None
    ) -> bool: ...

    async def rewind(self, step: NodeStep, *, owner: str, phase: StepPhase) -> bool:
        """A verified restore step that no longer verifies runs again."""
        ...

    async def reopen_after(self, operation_id: str, *, owner: str, epoch: int) -> bool:
        """The serving commit: the restore ends and the hold at `epoch`
        lifts in one transaction, or neither happens."""
        ...

    async def audit(
        self,
        action: AuditAction,
        *,
        target: str,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None: ...


ControlFor = Callable[[str], Awaitable[NodeControlPort | None]]


class _Lost(Exception):  # noqa: N818 - a state: another coordinator owns the operation
    pass


class _Later(Exception):  # noqa: N818 - a state: this node continues on the next pass
    pass


class MaintenanceCoordinator:
    def __init__(
        self,
        store: CoordinatorStore,
        control_for: ControlFor,
        *,
        owner: str | None = None,
        lease_s: float = 30.0,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._store = store
        self._control_for = control_for
        self.owner = owner or secrets.token_hex(16)
        self._lease_s = lease_s
        self._max_attempts = max_attempts

    async def run_once(self) -> bool:
        """One pass. True when there was an operation to work on."""
        operation = await self._store.claim(owner=self.owner, lease_s=self._lease_s)
        if operation is None:
            return False
        hold = await self._store.hold()
        if not hold.admission_closed or hold.epoch != operation.epoch:
            await self._abandon(operation, hold)
            return True

        running = [s for s in operation.steps if s.status is StepStatus.RUNNING]
        if running:
            renewing = asyncio.create_task(self._keep_lease(operation.id))
            try:
                await asyncio.gather(*(self._carry(operation, step) for step in running))
            finally:
                renewing.cancel()
                with suppress(asyncio.CancelledError):
                    await renewing
            refreshed = await self._store.get(operation.id)
            if refreshed is None:
                return True
            operation = refreshed

        if any(s.status is StepStatus.RUNNING for s in operation.steps):
            return True
        if operation.owner not in (None, self.owner):
            return True
        await self._close(operation)
        return True

    # -- one node -----------------------------------------------------------

    async def _carry(self, operation: MaintenanceOperation, step: NodeStep) -> None:
        control = await self._control_for(step.node_id)
        if control is None:
            await self._failed(
                step,
                NodeControlError("the node has no agent this coordinator can control"),
                final=True,
            )
            return
        advance = self._next_restore if operation.kind is OperationKind.RESTORE else self._next
        try:
            while step.status is StepStatus.RUNNING:
                step = await advance(operation, step, control)
        except _Lost:
            logger.warning("maintenance %s: another coordinator owns it now", operation.id)
        except _Later:
            return
        except NodeControlError as exc:
            await self._failed(
                step,
                exc,
                # A guard's refusal (unregistered, other weights, other
                # context) will not change on its own; neither will a
                # restart the supervisor reports failed.
                final=exc.refused in FINAL_REFUSALS or exc.status == 422,
                clear_reset_id=exc.refused == "restart_failed",
            )

    async def _next(
        self, operation: MaintenanceOperation, step: NodeStep, control: NodeControlPort
    ) -> NodeStep:
        """Do the step's next phase and record it; the step as it now is."""
        if step.phase is StepPhase.PENDING:
            report = await control.interrupt(operation.epoch)
            if not report.get("quiescent"):
                raise NodeControlError(
                    f"senders still talking to the runtime: {report.get('still_sending')}"
                )
            return await self._advance(step, StepPhase.INTERRUPTED, interrupt=report)

        if step.phase is StepPhase.INTERRUPTED:
            if step.snapshot_taken:
                return await self._advance(step, StepPhase.SNAPSHOTTED)
            resident = await control.residency()
            if resident is not None:
                return await self._advance(
                    step, StepPhase.SNAPSHOTTED, snapshot=snapshot_of(resident)
                )
            if step.attempts + 1 < SNAPSHOT_TRIES:
                raise NodeControlError("the runtime could not be observed for the snapshot")
            return await self._advance(
                step,
                StepPhase.SNAPSHOTTED,
                snapshot_error=(
                    "the runtime could not be observed before the reset; "
                    "it cannot be restored automatically"
                ),
            )

        if step.phase is StepPhase.SNAPSHOTTED:
            reset_id = step.reset_id
            if reset_id is None:
                reset_id = secrets.token_hex(16)
                if not await self._store.set_reset_id(step, owner=self.owner, reset_id=reset_id):
                    raise _Lost
            try:
                report = await control.reset(operation.epoch, reset_id, operator=COORDINATOR)
            except NodeControlError as exc:
                if exc.refused == "node_not_quiescent":
                    # A sender outlived the interrupt: interrupt again on the
                    # next pass. The snapshot is kept.
                    await self._advance(step, StepPhase.PENDING)
                    raise _Later from exc
                raise
            return await self._advance(
                step, StepPhase.RESET, reset=report, accounting=str(report.get("accounting"))
            )

        if step.phase is StepPhase.RESET:
            resident = await control.residency()
            if resident is None:
                raise NodeControlError("the restarted runtime does not answer yet")
            if resident:
                names = sorted(str(entry.get("name")) for entry in resident)
                raise NodeControlError(f"models are resident after the reset: {names}")
            done = await self._advance(
                step, StepPhase.VERIFIED, verification={"resident": [], "fresh": True}
            )
            await self._store.audit(
                AuditAction.MAINTENANCE_NODE_CLEARED,
                target=step.node_id,
                detail={
                    "epoch": str(operation.epoch),
                    "operation": operation.id,
                    "snapshot": _snapshot_summary(step),
                    "accounting": step.accounting or "unknown",
                    "reset_id": step.reset_id or "",
                },
            )
            return done

        raise AssertionError(f"no next phase from {step.phase}")

    # -- one node, restoring (P5) -------------------------------------------

    async def _next_restore(
        self, operation: MaintenanceOperation, step: NodeStep, control: NodeControlPort
    ) -> NodeStep:
        snapshot = restore_order(list(step.snapshot or []))
        progress: dict[str, Any] = dict(step.verification or {})
        loads: list[dict[str, Any]] = list(progress.get("loads") or [])

        if step.phase is StepPhase.PENDING:
            resident = await _observe(control)
            _no_strangers(snapshot, resident)
            missing = [m for m in snapshot if not resident_matches(m, resident)]
            if not missing:
                return await self._advance(
                    step, StepPhase.LOADED, verification=progress | {"probes": {}}
                )
            if len(loads) >= len(snapshot) * (1 + MAX_REPAIR_ROUNDS):
                raise NodeControlError(
                    f"still missing after {len(loads)} loads: {[m.get('name') for m in missing]}",
                    refused="repairs_exhausted",
                )
            model = missing[0]
            last = loads[-1] if loads else None
            if last is not None and last.get("name") == model.get("name") and not last.get("state"):
                op_id = str(last["op_id"])  # asked before and not answered: the same load
            else:
                op_id = f"restore-{operation.id[:16]}-{len(loads)}"
                loads.append({"op_id": op_id, "name": model.get("name")})
                step = await self._advance(step, StepPhase.PENDING, verification={"loads": loads})
            try:
                answer = await control.restore(
                    operation.epoch,
                    op_id,
                    action="load",
                    name=str(model.get("name")),
                    digest=model.get("digest"),
                    context_length=model.get("context_length"),
                )
            except NodeControlError as exc:
                if exc.body.get("state") == "failed":
                    loads[-1]["state"] = "failed"
                    await self._advance(step, StepPhase.PENDING, verification={"loads": loads})
                raise
            loads[-1]["state"] = answer.get("state")
            # Observed again on the next turn of the loop: a large load can
            # evict a sibling restored before it.
            return await self._advance(step, StepPhase.PENDING, verification={"loads": loads})

        if step.phase is StepPhase.LOADED:
            probes: dict[str, Any] = dict(progress.get("probes") or {})
            for index, model in enumerate(snapshot):
                name = str(model.get("name"))
                if probes.get(name) == "completed":
                    continue
                answer = await control.restore(
                    operation.epoch,
                    f"probe-{operation.id[:16]}-{len(loads)}-{index}",
                    action="probe",
                    name=name,
                    digest=model.get("digest"),
                    context_length=model.get("context_length"),
                )
                probes[name] = answer.get("state")
                step = await self._advance(
                    step, StepPhase.LOADED, verification=progress | {"probes": probes}
                )
            return await self._still_whole(step, snapshot, control, StepPhase.PROBED, progress)

        if step.phase is StepPhase.PROBED:
            done = await self._still_whole(step, snapshot, control, StepPhase.VERIFIED, progress)
            if done.phase is StepPhase.VERIFIED:
                await self._store.audit(
                    AuditAction.MAINTENANCE_NODE_RESTORED,
                    target=step.node_id,
                    detail={
                        "epoch": str(operation.epoch),
                        "operation": operation.id,
                        "models": ",".join(str(m.get("name")) for m in snapshot) or "none",
                        "loads": str(len(loads)),
                    },
                )
            return done

        raise AssertionError(f"no next restore phase from {step.phase}")

    async def _still_whole(
        self,
        step: NodeStep,
        snapshot: list[dict[str, Any]],
        control: NodeControlPort,
        then: StepPhase,
        progress: dict[str, Any],
    ) -> NodeStep:
        """Observe the whole node again: on to `then` if every saved model is
        still resident as recorded, back to loading if one was evicted."""
        resident = await _observe(control)
        _no_strangers(snapshot, resident)
        if all(resident_matches(m, resident) for m in snapshot):
            return await self._advance(
                step, then, verification=progress | {"resident": _names(resident)}
            )
        return await self._advance(
            step, StepPhase.PENDING, verification={"loads": progress.get("loads") or []}
        )

    async def _advance(self, step: NodeStep, phase: StepPhase, **values: Any) -> NodeStep:
        if not await self._store.advance(step, owner=self.owner, phase=phase, **values):
            raise _Lost
        operation = await self._store.get(step.operation_id)
        steps = operation.steps if operation is not None else ()
        current = next((s for s in steps if s.node_id == step.node_id), None)
        if current is None:
            raise _Lost
        return current

    async def _failed(
        self,
        step: NodeStep,
        exc: NodeControlError,
        *,
        final: bool = False,
        clear_reset_id: bool = False,
    ) -> None:
        updated = await self._store.attempt_failed(
            step,
            owner=self.owner,
            error=str(exc),
            max_attempts=self._max_attempts,
            clear_reset_id=clear_reset_id,
            final=final,
        )
        if updated is not None and updated.status is StepStatus.FAILED:
            logger.error("maintenance: node %s failed at %s: %s", step.node_id, step.phase, exc)
            await self._store.audit(
                AuditAction.MAINTENANCE_NODE_FAILED,
                target=step.node_id,
                outcome="failed",
                detail={"phase": step.phase.value, "error": str(exc)[:500]},
            )

    # -- the operation ------------------------------------------------------

    async def _keep_lease(self, operation_id: str) -> None:
        while True:
            await asyncio.sleep(self._lease_s / 3)
            if not await self._store.renew(operation_id, owner=self.owner, lease_s=self._lease_s):
                return

    async def _close(self, operation: MaintenanceOperation) -> None:
        if operation.kind is OperationKind.RESTORE:
            await self._close_restore(operation)
            return
        failed = [s for s in operation.steps if s.status is StepStatus.FAILED]
        detail = {
            "epoch": str(operation.epoch),
            "operation": operation.id,
            "nodes": str(len(operation.steps)),
        }
        if failed:
            error = "; ".join(f"{s.node_id} at {s.phase.value}: {s.error}" for s in failed)
            if await self._store.finish(
                operation.id, owner=self.owner, status=OperationStatus.FAILED, error=error[:2000]
            ):
                await self._store.audit(
                    AuditAction.MAINTENANCE_ENTRY_FAILED,
                    target="platform",
                    outcome="failed",
                    detail=detail | {"failed": str(len(failed))},
                )
            return
        unresolved = [s.node_id for s in operation.steps if s.accounting != "resolved"]
        succeeded = await self._store.finish(
            operation.id, owner=self.owner, status=OperationStatus.SUCCEEDED
        )
        if succeeded:
            await self._store.audit(
                AuditAction.MAINTENANCE_ENTRY_CLEARED,
                target="platform",
                detail=detail | {"accounting_unresolved": ",".join(unresolved)},
            )

    async def _close_restore(self, operation: MaintenanceOperation) -> None:
        failed = [s for s in operation.steps if s.status is StepStatus.FAILED]
        detail = {"epoch": str(operation.epoch), "operation": operation.id}
        if failed:
            error = "; ".join(f"{s.node_id} at {s.phase.value}: {s.error}" for s in failed)
            if await self._store.finish(
                operation.id, owner=self.owner, status=OperationStatus.FAILED, error=error[:2000]
            ):
                await self._store.audit(
                    AuditAction.MAINTENANCE_RESTORE_FAILED,
                    target="platform",
                    outcome="failed",
                    detail=detail | {"failed": str(len(failed))},
                )
            return
        # Every node verified on its own; now all of them at once, fresh,
        # immediately before the commit, so no node reopens on an
        # observation older than the others'.
        for step in operation.steps:
            control = await self._control_for(step.node_id)
            resident = await control.residency() if control is not None else None
            snapshot = list(step.snapshot or [])
            whole = resident is not None and all(resident_matches(m, resident) for m in snapshot)
            if not whole or (resident and _strangers(snapshot, resident)):
                logger.warning("maintenance restore: %s changed before reopening", step.node_id)
                await self._store.rewind(step, owner=self.owner, phase=StepPhase.PENDING)
                return
        if await self._store.reopen_after(operation.id, owner=self.owner, epoch=operation.epoch):
            await self._store.audit(
                AuditAction.MAINTENANCE_RESTORED,
                target="platform",
                detail=detail | {"nodes": str(len(operation.steps))},
            )

    async def _abandon(self, operation: MaintenanceOperation, hold: MaintenanceState) -> None:
        reason = (
            "the hold was lifted before the entry finished"
            if not hold.admission_closed
            else f"a later entry (epoch {hold.epoch}) superseded this one"
        )
        if await self._store.finish(
            operation.id, owner=self.owner, status=OperationStatus.ABANDONED, error=reason
        ):
            await self._store.audit(
                AuditAction.MAINTENANCE_ENTRY_ABANDONED,
                target="platform",
                outcome="failed",
                detail={"epoch": str(operation.epoch), "operation": operation.id, "reason": reason},
            )


async def _observe(control: NodeControlPort) -> list[dict[str, Any]]:
    resident = await control.residency()
    if resident is None:
        raise NodeControlError("the runtime could not be observed")
    return resident


def _names(resident: list[dict[str, Any]]) -> list[str]:
    return sorted(str(m.get("name")) for m in resident)


def _strangers(snapshot: list[dict[str, Any]], resident: list[dict[str, Any]]) -> list[str]:
    saved = {m.get("name") for m in snapshot}
    return sorted(str(m.get("name")) for m in resident if m.get("name") not in saved)


def _no_strangers(snapshot: list[dict[str, Any]], resident: list[dict[str, Any]]) -> None:
    """Under the hold nothing loads but the restore, so a model the snapshot
    did not hold is something this restore cannot account for."""
    strangers = _strangers(snapshot, resident)
    if strangers:
        raise NodeControlError(
            f"models the snapshot did not hold are resident: {strangers}",
            refused="unexpected_resident",
        )


def _snapshot_summary(step: NodeStep) -> str:
    if step.snapshot is None:
        return f"none: {step.snapshot_error}"
    return ",".join(str(entry.get("name")) for entry in step.snapshot) or "empty"
