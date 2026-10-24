"""The admin entrances' half of the maintenance gate (#61).

A route that can make the runtime do anything declares `require_serving`:
administrators' chat and assistant, knowledge search, document ingestion and
reindexing, and every model lifecycle action. During maintenance they answer
503 `maintenance` to everyone, platform administrators included; what an
administrator keeps is the management screens, not the models. The gateway
makes the same check inside API key authentication.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.adapters.persistence.repositories import PostgresMaintenanceRepository
from app.application.use_cases.manage_maintenance import assert_serving
from app.infrastructure.di import get_maintenance_repository


async def require_serving(
    maintenance: Annotated[PostgresMaintenanceRepository, Depends(get_maintenance_repository)],
) -> None:
    await assert_serving(maintenance)


SERVING = [Depends(require_serving)]
"""For `dependencies=` on a route decorator."""
