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
    OperationStatus,
    StepPhase,
    StepStatus,
    snapshot_of,
)
from app.domain.ports.node_control_port import NodeControlError, NodeControlPort

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
        try:
            while step.status is StepStatus.RUNNING:
                step = await self._next(operation, step, control)
        except _Lost:
            logger.warning("maintenance %s: another coordinator owns it now", operation.id)
        except _Later:
            return
        except NodeControlError as exc:
            await self._failed(
                step,
                exc,
                final=exc.refused == "restart_failed",
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


def _snapshot_summary(step: NodeStep) -> str:
    if step.snapshot is None:
        return f"none: {step.snapshot_error}"
    return ",".join(str(entry.get("name")) for entry in step.snapshot) or "empty"
