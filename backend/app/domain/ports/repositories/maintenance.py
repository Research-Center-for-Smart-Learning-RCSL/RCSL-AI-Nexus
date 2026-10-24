"""Port for the maintenance hold (#61)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.entities.maintenance import MaintenanceState


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
