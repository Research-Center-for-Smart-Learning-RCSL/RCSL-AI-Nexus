"""Maintenance hold (#61): what the public page may see, and what an
administrator sees."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities.maintenance import MAX_MESSAGE_LENGTH, MaintenanceState


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

    @classmethod
    def of(cls, state: MaintenanceState, *, enabled: bool) -> MaintenanceStatusResponse:
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
        )


class EnterMaintenanceRequest(BaseModel):
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    expected_return_at: datetime | None = None


class MaintenanceMessageRequest(BaseModel):
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    expected_return_at: datetime | None = None
    expected_revision: int = Field(ge=0)
