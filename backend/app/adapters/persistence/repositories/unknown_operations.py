"""The node operations whose outcome is unknown, for the admin's reset action (#61).

Read-only. The node agent owns `node_operations` and is the only writer; an
administrator clears one only through the agent's supervised reset.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.maintenance_operation import UnknownOperation


class PostgresUnknownOperations:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[UnknownOperation]:
        rows = await self._session.execute(
            text(
                "SELECT node_id, op_id, kind, reason, submitted_at FROM node_operations "
                "WHERE state = 'outcome_unknown' ORDER BY node_id, submitted_at"
            )
        )
        return [UnknownOperation(**row) for row in rows.mappings()]
