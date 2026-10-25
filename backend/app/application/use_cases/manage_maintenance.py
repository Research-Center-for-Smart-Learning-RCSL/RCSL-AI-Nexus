"""Closing and reopening the platform (#61).

What an entry closes at once: every entrance refuses everyone except platform
administrators, every non-admin local session dies, API keys and every
inference path (administrators' included) answer 503 `maintenance`, and the
residency reconciler stands down. In the same transaction it records an
operation with one step per node, which the maintenance coordinator in the
tailnet admin then carries out: interrupt, snapshot, reset and verify every
runtime empty (P4, `maintenance_coordinator.py`). Restoring the snapshot
before reopening is P5, and until it exists and has passed on the host,
entering stays behind `maintenance_enabled`: a hold that cannot bring the
models back is not the maintenance #61 asks for.

An entry is refused before anything closes if any node is reached without an
agent: that runtime could not be interrupted or released, and the platform
would be closed to users while it kept working.

Entering and reopening are idempotent rather than conditional on a revision.
A second press of either button, from the same administrator or another, finds
the platform already where it was asked to be and returns that state; only
the message, which two people could be editing at once, is revision-checked.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.maintenance import MAX_MESSAGE_LENGTH, MaintenanceState
from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    OperationKind,
    OperationStatus,
)
from app.domain.exceptions import (
    MaintenanceDisabledError,
    MaintenanceError,
    MaintenanceStateConflictError,
    MaintenanceUnsupportedError,
    NotAuthorizedError,
)
from app.domain.ports.repositories import (
    MaintenanceOperationsPort,
    MaintenanceRepositoryPort,
    NodeRepositoryPort,
)
from app.domain.ports.security_ports import AuditPort, AuthorizationPort


class ManageMaintenance:
    def __init__(
        self,
        maintenance: MaintenanceRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        *,
        enabled: bool,
        operations: MaintenanceOperationsPort | None = None,
        nodes: NodeRepositoryPort | None = None,
        agents_enabled: bool = False,
    ) -> None:
        self._maintenance = maintenance
        self._authz = authz
        self._audit = audit
        self._enabled = enabled
        self._operations = operations
        self._nodes = nodes
        self._agents_enabled = agents_enabled

    async def public_status(self) -> MaintenanceState:
        """No actor: this is what the maintenance page polls. The router
        decides which fields of it leave the process."""
        return await self._maintenance.read()

    async def status(self, actor: Actor) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_READ)
        return await self._maintenance.read()

    async def operation(self, actor: Actor) -> MaintenanceOperation | None:
        """The latest entry and how far each node has got. Privileged: it
        names the nodes and the models they held."""
        self._require(actor, Scope.MAINTENANCE_READ)
        if self._operations is None:
            return None
        return await self._operations.latest()

    async def enter(
        self, actor: Actor, *, message: str | None, expected_return_at: datetime | None
    ) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        if not self._enabled:
            raise MaintenanceDisabledError(detail="MAINTENANCE_ENABLED is off")
        if self._operations is None or self._nodes is None or not self._agents_enabled:
            raise MaintenanceUnsupportedError(
                detail="maintenance needs node agents: NODE_AGENT_ENABLED is off"
            )
        nodes = await self._nodes.list_all()
        direct = sorted(n.name for n in nodes if not n.agent_url)
        if direct:
            raise MaintenanceUnsupportedError(detail=f"nodes without an agent: {direct}")

        closed = await self._maintenance.close(
            changed_by=actor.id,
            message=_clean(message),
            expected_return_at=expected_return_at,
        )
        if closed is None:
            return await self._maintenance.read()

        operation = await self._operations.create_entry(
            epoch=closed.epoch, requested_by=actor.id, node_ids=[n.id for n in nodes]
        )
        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_ENTERED,
            target="platform",
            detail={
                "epoch": str(closed.epoch),
                "operation": operation.id,
                "nodes": str(len(nodes)),
            },
        )
        return closed

    async def restore(self, actor: Actor) -> MaintenanceOperation:
        """Put back what the entry released, verify it, then reopen (P5).

        Only from an entry that succeeded under the hold now closed: every
        node released and verified empty, with a snapshot to restore and its
        unknowns resolved. A node without a snapshot, or with unknowns left,
        is refused here with the reason, because a restore that skipped it
        would reopen a platform that is not what it was. Reopening without a
        restore stays available for that case. Pressed again while a restore
        runs, it returns that restore.
        """
        self._require(actor, Scope.MAINTENANCE_WRITE)
        operations = self._operations
        state = await self._maintenance.read()
        if operations is None or not state.admission_closed:
            raise MaintenanceStateConflictError(detail="the platform is not closed")
        running = await operations.latest_of(OperationKind.RESTORE, state.epoch)
        if running is not None:
            if running.status is OperationStatus.RUNNING:
                return running
            raise MaintenanceStateConflictError(
                detail=f"this hold's restore is {running.status.value}; retry it instead"
            )
        entry = await operations.latest_of(OperationKind.ENTER, state.epoch)
        if entry is None or entry.status is not OperationStatus.SUCCEEDED:
            raise MaintenanceStateConflictError(
                detail="the entry has not released every runtime yet"
                if entry is not None
                else "this hold has no entry to restore"
            )
        missing = [s.node_id for s in entry.steps if s.snapshot is None]
        if missing:
            raise MaintenanceStateConflictError(
                detail=f"no snapshot for {missing}: load those models by hand, "
                "or reopen without restoring"
            )
        unresolved = [s.node_id for s in entry.steps if s.accounting != "resolved"]
        if unresolved:
            raise MaintenanceStateConflictError(
                detail=f"unresolved unknown operations on {unresolved}: resolve them first"
            )
        restore = await operations.create_restore(
            epoch=state.epoch,
            requested_by=actor.id,
            snapshots={s.node_id: list(s.snapshot or []) for s in entry.steps},
        )
        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_RESTORE_STARTED,
            target="platform",
            detail={"epoch": str(state.epoch), "operation": restore.id},
        )
        return restore

    async def retry(self, actor: Actor) -> MaintenanceOperation:
        """Run a failed entry's failed steps again from where they stopped.

        Only the latest entry, and only while the hold it was made under is
        still closed: retrying an entry for a platform since reopened would
        release runtimes nobody asked to release.
        """
        self._require(actor, Scope.MAINTENANCE_WRITE)
        operations = self._operations
        if operations is None:
            raise MaintenanceStateConflictError(detail="there is no failed entry to retry")
        operation = await operations.latest()
        if operation is None or operation.status is not OperationStatus.FAILED:
            raise MaintenanceStateConflictError(detail="there is no failed entry to retry")
        state = await self._maintenance.read()
        if not state.admission_closed or state.epoch != operation.epoch:
            raise MaintenanceStateConflictError(
                detail=f"the entry was for epoch {operation.epoch}, and that hold is not current"
            )
        if not await operations.retry(operation.id):
            raise MaintenanceStateConflictError(detail="the entry is no longer failed")
        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_RETRIED,
            target="platform",
            detail={"epoch": str(operation.epoch), "operation": operation.id},
        )
        return await operations.get(operation.id) or operation

    async def reopen(self, actor: Actor) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        opened = await self._maintenance.reopen(changed_by=actor.id)
        if opened is None:
            return await self._maintenance.read()

        # Never refused, so a hold can always be lifted, even one whose entry
        # never finished; but an entry still releasing runtimes must stop
        # with it, or it could restart a runtime the platform is serving on.
        abandoned = (
            await self._operations.abandon_running("the platform was reopened")
            if self._operations is not None
            else []
        )
        await self._audit.record(
            actor,
            AuditAction.MAINTENANCE_REOPENED,
            target="platform",
            detail={"epoch": str(opened.epoch), "abandoned": ",".join(abandoned)},
        )
        return opened

    async def set_message(
        self,
        actor: Actor,
        *,
        message: str | None,
        expected_return_at: datetime | None,
        expected_revision: int,
    ) -> MaintenanceState:
        self._require(actor, Scope.MAINTENANCE_WRITE)
        saved = await self._maintenance.set_message(
            changed_by=actor.id,
            message=_clean(message),
            expected_return_at=expected_return_at,
            expected_revision=expected_revision,
        )
        if saved is None:
            raise MaintenanceStateConflictError(
                detail=f"revision {expected_revision} is no longer current"
            )
        await self._audit.record(actor, AuditAction.MAINTENANCE_MESSAGE_SET, target="platform")
        return saved

    def _require(self, actor: Actor, scope: Scope) -> None:
        """The scope, and the live role behind it.

        The scopes are admin-only already; the role is checked as well because
        the hold's whole contract is "platform administrators, and nobody
        else", and an API key's actor (role `service`) must never reach here
        whatever a future scope table says.
        """
        self._authz.require(actor, scope)
        if actor.role is not Role.ADMIN:
            raise NotAuthorizedError(detail=f"maintenance needs a platform admin, not {actor.role}")


async def assert_serving(maintenance: MaintenanceRepositoryPort) -> None:
    """Raise `MaintenanceError` while the platform is closed.

    The one check every path that spends the runtime makes: gateway keys,
    administrators' chat and assistant, embeddings, model lifecycle and the
    detached jobs. Platform administrators are not exempt; they keep the
    management screens, not the models.
    """
    state = await maintenance.read()
    if state.admission_closed:
        raise MaintenanceError(detail=f"maintenance epoch {state.epoch}")


def _clean(message: str | None) -> str | None:
    if message is None:
        return None
    message = message.strip()
    if not message:
        return None
    return message[:MAX_MESSAGE_LENGTH]
