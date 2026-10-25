"""PostgreSQL holds the maintenance hold (#61), and only admin roles write it.

Every change is one conditional `UPDATE ... RETURNING` on the singleton row,
never a read followed by a write, so concurrent presses cannot both succeed and
an edit made against a stale read cannot land. `changed_at` is the database's
clock, the one the rest of the control plane stamps with.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.sqlalchemy_models.maintenance import (
    SINGLETON_ID,
    MaintenanceControlRow,
)
from app.domain.entities.maintenance import FENCE_LOCK, MaintenancePhase, MaintenanceState

_ROW = MaintenanceControlRow


class PostgresMaintenanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self) -> MaintenanceState:
        row = (
            await self._session.execute(select(_ROW).where(_ROW.id == SINGLETON_ID))
        ).scalar_one_or_none()
        if row is None:
            # The migration seeds the row, so its absence is a schema that
            # has not been migrated. Failing closed here would lock every
            # administrator out of the screen that could explain it; failing
            # loudly is what the migrate job already does on its own.
            raise RuntimeError("maintenance_control has no row; run the migrations")
        return _state(row)

    async def close(
        self, *, changed_by: str, message: str | None, expected_return_at: datetime | None
    ) -> MaintenanceState | None:
        # Waits for promotions already reading the hold to commit, and makes
        # every later one read it closed (`FENCE_LOCK`). Released at commit.
        await self._session.execute(select(func.pg_advisory_xact_lock(*FENCE_LOCK)))
        return await self._change(
            _ROW.admission_closed.is_(False),
            admission_closed=True,
            phase=MaintenancePhase.MAINTENANCE.value,
            epoch=_ROW.epoch + 1,
            message=message,
            expected_return_at=expected_return_at,
            changed_by=changed_by,
        )

    async def reopen(self, *, changed_by: str) -> MaintenanceState | None:
        return await self._change(
            _ROW.admission_closed.is_(True),
            admission_closed=False,
            phase=MaintenancePhase.NORMAL.value,
            changed_by=changed_by,
        )

    async def set_message(
        self,
        *,
        changed_by: str,
        message: str | None,
        expected_return_at: datetime | None,
        expected_revision: int,
    ) -> MaintenanceState | None:
        return await self._change(
            _ROW.revision == expected_revision,
            message=message,
            expected_return_at=expected_return_at,
            changed_by=changed_by,
        )

    async def _change(self, condition: Any, **values: Any) -> MaintenanceState | None:
        statement = (
            update(_ROW)
            .where(_ROW.id == SINGLETON_ID, condition)
            .values(revision=_ROW.revision + 1, changed_at=func.now(), **values)
            .returning(_ROW)
            .execution_options(synchronize_session=False)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _state(row) if row is not None else None


def _state(row: MaintenanceControlRow) -> MaintenanceState:
    return MaintenanceState(
        admission_closed=row.admission_closed,
        phase=MaintenancePhase(row.phase),
        epoch=row.epoch,
        revision=row.revision,
        message=row.message,
        expected_return_at=row.expected_return_at,
        changed_by=row.changed_by,
        changed_at=row.changed_at,
    )
