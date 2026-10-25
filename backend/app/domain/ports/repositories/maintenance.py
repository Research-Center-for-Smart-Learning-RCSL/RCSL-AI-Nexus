"""Port for the maintenance hold (#61)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.domain.entities.maintenance import MaintenanceState
from app.domain.entities.maintenance_operation import (
    MaintenanceOperation,
    NodeStep,
    OperationKind,
    OperationStatus,
    StepPhase,
)


class MaintenanceRepositoryPort(Protocol):
    async def read(self) -> MaintenanceState: ...

    async def close(
        self, *, changed_by: str, message: str | None, expected_return_at: datetime | None
    ) -> MaintenanceState | None:
        """Close and open a new epoch, or None if the platform was already
        closed. One conditional statement, so two administrators pressing the
        button at once produce one entry and one epoch."""
        ...

    async def reopen(self, *, changed_by: str) -> MaintenanceState | None:
        """Open, or None if it was already open. The epoch is kept."""
        ...

    async def set_message(
        self,
        *,
        changed_by: str,
        message: str | None,
        expected_return_at: datetime | None,
        expected_revision: int,
    ) -> MaintenanceState | None:
        """None if the revision moved since the caller read it."""
        ...


class MaintenanceOperationsPort(Protocol):
    """What an entry does to each node (P4); see `maintenance_operation.py`."""

    async def create_entry(
        self, *, epoch: int, requested_by: str, node_ids: list[str]
    ) -> MaintenanceOperation: ...

    async def create_restore(
        self, *, epoch: int, requested_by: str, snapshots: dict[str, list[dict[str, Any]]]
    ) -> MaintenanceOperation: ...

    async def latest_of(self, kind: OperationKind, epoch: int) -> MaintenanceOperation | None: ...

    async def get(self, operation_id: str) -> MaintenanceOperation | None: ...

    async def latest(self) -> MaintenanceOperation | None: ...

    async def claim(self, *, owner: str, lease_s: float) -> MaintenanceOperation | None: ...

    async def renew(self, operation_id: str, *, owner: str, lease_s: float) -> bool: ...

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

    async def rewind(self, step: NodeStep, *, owner: str, phase: StepPhase) -> bool: ...

    async def abandon_running(self, reason: str) -> list[str]: ...

    async def retry(self, operation_id: str) -> bool: ...
