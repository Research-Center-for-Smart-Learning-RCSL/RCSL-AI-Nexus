"""Usage over time, for the analytics charts.

Behind `usage:read_all`, the same scope the dashboard totals use, because these
are the tenant's aggregate figures rather than one caller's own.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.use_cases.read_usage_analytics import ReadUsageAnalytics, UsageWindow
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_usage_analytics
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import UsageAnalyticsResponse

router = APIRouter(tags=["usage"])


@router.get("/usage")
async def read_usage(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadUsageAnalytics, Depends(build_read_usage_analytics)],
    window: Annotated[UsageWindow, Query(alias="range")] = "24h",
) -> UsageAnalyticsResponse:
    return UsageAnalyticsResponse.of(await use_case.execute(actor, window=window))
