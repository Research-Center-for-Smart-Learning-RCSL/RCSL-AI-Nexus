"""The overview figures."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.read_dashboard import ReadDashboard
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_dashboard
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import DashboardResponse

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def read_dashboard(
    actor: Annotated[Actor, Depends(current_actor)],
    dashboard: Annotated[ReadDashboard, Depends(build_read_dashboard)],
) -> DashboardResponse:
    return DashboardResponse(**asdict(await dashboard.execute(actor)))
