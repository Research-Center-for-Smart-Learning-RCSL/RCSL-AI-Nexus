"""Maintenance operations and their node steps (P4 on #61), in PostgreSQL.

**Ownership is a lease, and every write is fenced on it.** A coordinator claims
a running operation by writing its own id and a lease expiry, renews the lease
while it works, and may take over another's only once that lease has expired.
Each step write carries `owner = :me` in the same statement, so a coordinator
that lost its lease while waiting on a node cannot write over its successor's
progress. Expiry permits a takeover; it proves nothing about the runtime, which
is why a step is retried from what was recorded, never assumed done.

Raw SQL, like the node agent's tables: the coordinator never holds a row lock
across a call to a node, and each method here is one short statement.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    NodeStep,
    OperationKind,
    OperationStatus,
    StepPhase,
    StepStatus,
)


class PostgresMaintenanceOperations:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- the entry, in the administrator's transaction ----------------------

    async def create_entry(
        self, *, epoch: int, requested_by: str, node_ids: list[str]
    ) -> MaintenanceOperation:
        """Recorded in the same transaction that closes the hold, so an
        entry that committed always has an operation to carry it out."""
        operation_id = uuid.uuid4().hex
        await self._session.execute(
            text(
                "INSERT INTO maintenance_operations (id, kind, epoch, status, requested_by) "
                "VALUES (:id, :kind, :epoch, 'running', :requested_by)"
            ),
            {
                "id": operation_id,
                "kind": OperationKind.ENTER.value,
                "epoch": epoch,
                "requested_by": requested_by,
            },
        )
        for node_id in node_ids:
            await self._session.execute(
                text(
                    "INSERT INTO maintenance_node_steps (operation_id, node_id, phase, status) "
                    "VALUES (:operation_id, :node_id, 'pending', 'running')"
                ),
                {"operation_id": operation_id, "node_id": node_id},
            )
        found = await self.get(operation_id)
        if found is None:
            raise RuntimeError(f"maintenance operation {operation_id} vanished after insert")
        return found

    # -- reads --------------------------------------------------------------

    async def get(self, operation_id: str) -> MaintenanceOperation | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, kind, epoch, status, requested_by, owner, lease_expires_at, "
                        "error, created_at, updated_at, finished_at "
                        "FROM maintenance_operations WHERE id = :id"
                    ),
                    {"id": operation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _operation(row, await self._steps(operation_id))

    async def latest(self) -> MaintenanceOperation | None:
        operation_id = (
            await self._session.execute(
                text("SELECT id FROM maintenance_operations ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar_one_or_none()
        return await self.get(operation_id) if operation_id is not None else None

    async def _steps(self, operation_id: str) -> tuple[NodeStep, ...]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT operation_id, node_id, phase, status, attempts, interrupt, snapshot, "
                    "snapshot_at, snapshot_error, reset_id, reset, accounting, verification, "
                    "error, updated_at FROM maintenance_node_steps "
                    "WHERE operation_id = :id ORDER BY node_id"
                ),
                {"id": operation_id},
            )
        ).mappings()
        return tuple(_step(row) for row in rows)

    # -- the coordinator's claim --------------------------------------------

    async def claim(self, *, owner: str, lease_s: float) -> MaintenanceOperation | None:
        """The oldest running operation, if no other coordinator holds a live
        lease on it. Renewing one's own lease is the same statement."""
        operation_id = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_operations SET owner = :owner, "
                    "lease_expires_at = now() + make_interval(secs => :lease), "
                    "updated_at = now() "
                    "WHERE id = (SELECT id FROM maintenance_operations "
                    "WHERE status = 'running' AND (owner IS NULL OR owner = :owner "
                    "OR lease_expires_at < now()) "
                    "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) "
                    "RETURNING id"
                ),
                {"owner": owner, "lease": lease_s},
            )
        ).scalar_one_or_none()
        return await self.get(operation_id) if operation_id is not None else None

    async def renew(self, operation_id: str, *, owner: str, lease_s: float) -> bool:
        renewed = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_operations SET "
                    "lease_expires_at = now() + make_interval(secs => :lease) "
                    "WHERE id = :operation_id AND owner = :owner AND status = 'running' "
                    "RETURNING id"
                ),
                {"operation_id": operation_id, "owner": owner, "lease": lease_s},
            )
        ).scalar_one_or_none()
        return renewed is not None

    # -- step writes, fenced on the owner -----------------------------------

    async def advance(self, step: NodeStep, *, owner: str, phase: StepPhase, **values: Any) -> bool:
        """Move a step to `phase` with what that phase recorded, and reset its
        attempt count. A column not given keeps its value.

        `snapshot` and `snapshot_error` are written only if neither was before:
        the original is what P5 restores, and a retry must never replace it
        with a runtime it has already started to empty. Every SET expression
        reads the row as it was, so the snapshot's three columns agree.
        """
        unknown = set(values) - _STEP_VALUES
        if unknown:
            raise ValueError(f"not step columns: {sorted(unknown)}")
        params: dict[str, Any] = {
            "operation_id": step.operation_id,
            "node_id": step.node_id,
            "owner": owner,
            "phase": phase.value,
            "accounting": values.get("accounting"),
            "snapshot_error": values.get("snapshot_error"),
        }
        for column in _JSON:
            params[column] = json.dumps(values[column]) if column in values else None
        done = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_node_steps SET phase = CAST(:phase AS varchar), "
                    "attempts = 0, error = NULL, updated_at = now(), "
                    "status = CASE WHEN CAST(:phase AS varchar) = 'verified' THEN 'done' "
                    "ELSE status END, "
                    "interrupt = COALESCE(CAST(:interrupt AS jsonb), interrupt), "
                    "reset = COALESCE(CAST(:reset AS jsonb), reset), "
                    "verification = COALESCE(CAST(:verification AS jsonb), verification), "
                    "accounting = COALESCE(CAST(:accounting AS text), accounting), "
                    "snapshot = CASE WHEN snapshot IS NULL AND snapshot_error IS NULL "
                    "THEN CAST(:snapshot AS jsonb) ELSE snapshot END, "
                    "snapshot_error = CASE WHEN snapshot IS NULL AND snapshot_error IS NULL "
                    "THEN CAST(:snapshot_error AS text) ELSE snapshot_error END, "
                    "snapshot_at = CASE WHEN snapshot IS NULL AND snapshot_error IS NULL "
                    "AND (CAST(:snapshot AS jsonb) IS NOT NULL "
                    "OR CAST(:snapshot_error AS text) IS NOT NULL) "
                    "THEN now() ELSE snapshot_at END "
                    "WHERE operation_id = :operation_id AND node_id = :node_id "
                    "AND status = 'running' AND EXISTS (SELECT 1 FROM maintenance_operations o "
                    "WHERE o.id = :operation_id AND o.owner = :owner AND o.status = 'running') "
                    "RETURNING node_id"
                ),
                params,
            )
        ).scalar_one_or_none()
        return done is not None

    async def set_reset_id(self, step: NodeStep, *, owner: str, reset_id: str) -> bool:
        done = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_node_steps SET reset_id = :reset_id, updated_at = now() "
                    "WHERE operation_id = :operation_id AND node_id = :node_id "
                    "AND reset_id IS NULL AND EXISTS (SELECT 1 FROM maintenance_operations o "
                    "WHERE o.id = :operation_id AND o.owner = :owner AND o.status = 'running') "
                    "RETURNING node_id"
                ),
                {
                    "operation_id": step.operation_id,
                    "node_id": step.node_id,
                    "owner": owner,
                    "reset_id": reset_id,
                },
            )
        ).scalar_one_or_none()
        return done is not None

    async def attempt_failed(
        self,
        step: NodeStep,
        *,
        owner: str,
        error: str,
        max_attempts: int,
        clear_reset_id: bool = False,
        final: bool = False,
    ) -> NodeStep | None:
        """Count a failed attempt; the step fails once it has used them all,
        or at once when `final`. `clear_reset_id` makes the next attempt a new
        restart, for a restart the supervisor reported as failed."""
        row = (
            (
                await self._session.execute(
                    text(
                        "UPDATE maintenance_node_steps SET attempts = attempts + 1, "
                        "error = :error, updated_at = now(), "
                        "reset_id = CASE WHEN :clear THEN NULL ELSE reset_id END, "
                        "status = CASE WHEN :final OR attempts + 1 >= :max THEN 'failed' "
                        "ELSE status END "
                        "WHERE operation_id = :operation_id AND node_id = :node_id "
                        "AND status = 'running' AND EXISTS (SELECT 1 FROM maintenance_operations o "
                        "WHERE o.id = :operation_id AND o.owner = :owner AND o.status = 'running') "
                        "RETURNING operation_id, node_id, phase, status, attempts, interrupt, "
                        "snapshot, snapshot_at, snapshot_error, reset_id, reset, accounting, "
                        "verification, error, updated_at"
                    ),
                    {
                        "operation_id": step.operation_id,
                        "node_id": step.node_id,
                        "owner": owner,
                        "error": error[:2000],
                        "max": max_attempts,
                        "clear": clear_reset_id,
                        "final": final,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return _step(row) if row is not None else None

    # -- the operation's end ------------------------------------------------

    async def finish(
        self, operation_id: str, *, owner: str, status: OperationStatus, error: str | None = None
    ) -> bool:
        done = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_operations SET status = :status, error = :error, "
                    "owner = NULL, lease_expires_at = NULL, updated_at = now(), "
                    "finished_at = now() "
                    "WHERE id = :operation_id AND owner = :owner AND status = 'running' "
                    "RETURNING id"
                ),
                {
                    "operation_id": operation_id,
                    "owner": owner,
                    "status": status.value,
                    "error": error,
                },
            )
        ).scalar_one_or_none()
        return done is not None

    async def abandon_running(self, reason: str) -> list[str]:
        """End every running entry, in the transaction that reopens the
        platform: its coordinator's fenced writes stop landing at once, and
        the agent refuses a reset for a hold that is no longer closed."""
        rows = await self._session.execute(
            text(
                "UPDATE maintenance_operations SET status = 'abandoned', error = :reason, "
                "owner = NULL, lease_expires_at = NULL, updated_at = now(), "
                "finished_at = now() WHERE status = 'running' RETURNING id"
            ),
            {"reason": reason},
        )
        return [str(r[0]) for r in rows]

    async def retry(self, operation_id: str) -> bool:
        """An administrator's retry of a failed entry: its failed steps run
        again from the phase they reached, with what they recorded kept."""
        reopened = (
            await self._session.execute(
                text(
                    "UPDATE maintenance_operations SET status = 'running', error = NULL, "
                    "owner = NULL, lease_expires_at = NULL, finished_at = NULL, "
                    "updated_at = now() WHERE id = :id AND status = 'failed' RETURNING id"
                ),
                {"id": operation_id},
            )
        ).scalar_one_or_none()
        if reopened is None:
            return False
        await self._session.execute(
            text(
                "UPDATE maintenance_node_steps SET status = 'running', attempts = 0, "
                "updated_at = now() WHERE operation_id = :id AND status = 'failed'"
            ),
            {"id": operation_id},
        )
        return True


_JSON = frozenset({"interrupt", "snapshot", "reset", "verification"})
_STEP_VALUES = _JSON | {"snapshot_error", "accounting"}


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _operation(row: Any, steps: tuple[NodeStep, ...]) -> MaintenanceOperation:
    return MaintenanceOperation(
        id=row["id"],
        kind=OperationKind(row["kind"]),
        epoch=row["epoch"],
        status=OperationStatus(row["status"]),
        requested_by=row["requested_by"],
        owner=row["owner"],
        lease_expires_at=row["lease_expires_at"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        steps=steps,
    )


def _step(row: Any) -> NodeStep:
    snapshot_at: datetime | None = row["snapshot_at"]
    return NodeStep(
        operation_id=row["operation_id"],
        node_id=row["node_id"],
        phase=StepPhase(row["phase"]),
        status=StepStatus(row["status"]),
        attempts=row["attempts"],
        interrupt=_json(row["interrupt"]),
        snapshot=_json(row["snapshot"]),
        snapshot_at=snapshot_at,
        snapshot_error=row["snapshot_error"],
        reset_id=row["reset_id"],
        reset=_json(row["reset"]),
        accounting=row["accounting"],
        verification=_json(row["verification"]),
        error=row["error"],
        updated_at=row["updated_at"],
    )
