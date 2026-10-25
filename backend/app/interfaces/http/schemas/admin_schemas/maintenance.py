"""Maintenance hold (#61): what the public page may see, and what an
administrator sees."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.entities.maintenance import MAX_MESSAGE_LENGTH, MaintenanceState
from app.domain.entities.maintenance_operation import MaintenanceOperation, NodeStep


class PublicMaintenanceStatusResponse(BaseModel):
    """Answered without authentication, so it carries nothing about who closed
    the platform, which models it held, or anything about the infrastructure:
    whether it is closed, what the administrators chose to say, and when they
    expect to be back."""

    closed: bool
    phase: str
    message: str | None
    expected_return_at: datetime | None
    revision: int
    """So an open page can tell that something changed without diffing."""

    @classmethod
    def of(cls, state: MaintenanceState) -> PublicMaintenanceStatusResponse:
        return cls(
            closed=state.admission_closed,
            phase=state.phase.value,
            message=state.message if state.admission_closed else None,
            expected_return_at=state.expected_return_at if state.admission_closed else None,
            revision=state.revision,
        )


class MaintenanceNodeStepView(BaseModel):
    """One node's progress through an entry. Administrators only: it names
    the models the node held and the evidence its reset left."""

    node_id: str
    phase: str
    status: str
    attempts: int
    error: str | None
    snapshot: list[dict[str, Any]] | None
    snapshot_at: datetime | None
    snapshot_error: str | None
    interrupted: list[str]
    accounting: str | None
    reset: dict[str, Any] | None
    updated_at: datetime | None

    @classmethod
    def of(cls, step: NodeStep) -> MaintenanceNodeStepView:
        interrupted = (step.interrupt or {}).get("interrupted") or []
        return cls(
            node_id=step.node_id,
            phase=step.phase.value,
            status=step.status.value,
            attempts=step.attempts,
            error=step.error,
            snapshot=step.snapshot,
            snapshot_at=step.snapshot_at,
            snapshot_error=step.snapshot_error,
            interrupted=[str(op) for op in interrupted],
            accounting=step.accounting,
            reset=step.reset,
            updated_at=step.updated_at,
        )


class MaintenanceOperationView(BaseModel):
    id: str
    kind: str
    epoch: int
    status: str
    requested_by: str
    error: str | None
    created_at: datetime | None
    finished_at: datetime | None
    nodes: list[MaintenanceNodeStepView]

    @classmethod
    def of(cls, operation: MaintenanceOperation) -> MaintenanceOperationView:
        return cls(
            id=operation.id,
            kind=operation.kind.value,
            epoch=operation.epoch,
            status=operation.status.value,
            requested_by=operation.requested_by,
            error=operation.error,
            created_at=operation.created_at,
            finished_at=operation.finished_at,
            nodes=[MaintenanceNodeStepView.of(step) for step in operation.steps],
        )


class MaintenanceStatusResponse(BaseModel):
    closed: bool
    phase: str
    epoch: int
    revision: int
    message: str | None
    expected_return_at: datetime | None
    changed_by: str | None
    changed_at: datetime | None
    enabled: bool
    """Whether this deployment lets an administrator enter maintenance. Reopen
    is offered whatever this says."""
    operation: MaintenanceOperationView | None = None
    """The latest entry and each node's progress through it: access closes
    at once, the runtimes are released after, and this is the second part."""

    @classmethod
    def of(
        cls,
        state: MaintenanceState,
        *,
        enabled: bool,
        operation: MaintenanceOperation | None = None,
    ) -> MaintenanceStatusResponse:
        return cls(
            closed=state.admission_closed,
            phase=state.phase.value,
            epoch=state.epoch,
            revision=state.revision,
            message=state.message,
            expected_return_at=state.expected_return_at,
            changed_by=state.changed_by,
            changed_at=state.changed_at,
            enabled=enabled,
            operation=MaintenanceOperationView.of(operation) if operation else None,
        )


class EnterMaintenanceRequest(BaseModel):
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    expected_return_at: datetime | None = None


class MaintenanceMessageRequest(BaseModel):
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    expected_return_at: datetime | None = None
    expected_revision: int = Field(ge=0)
