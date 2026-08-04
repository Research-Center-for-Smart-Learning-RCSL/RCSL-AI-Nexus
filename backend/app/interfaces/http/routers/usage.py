"""Usage over time, for the analytics charts.

Two endpoints, because there are two questions and two scopes. `/usage` is the
tenant's aggregate figures behind `usage:read_all`, the same scope the dashboard
totals use. `/usage/me` is the caller's own behind `usage:read_own`, which every
human role holds and nothing required until 2026-08-04.

Separate paths rather than one that quietly returns less to a narrower caller:
a chart that silently changes what it counts based on who is looking is one
nobody can compare with anyone else's.
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


# Declared after `/usage` and before nothing else that could shadow it. `/me` is
# a fixed segment on a router with no `/usage/{id}` route, so there is no
# ambiguity to resolve — worth stating because adding one later would create it.
@router.get("/usage/me")
async def read_own_usage(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadUsageAnalytics, Depends(build_read_usage_analytics)],
    window: Annotated[UsageWindow, Query(alias="range")] = "24h",
) -> UsageAnalyticsResponse:
    """The caller's own usage, in the shape the same charts already render.

    The identity comes from the resolved actor, never from a parameter: an
    endpoint that took a user id here would be `usage:read_all` wearing a
    narrower name, and the scope it checks would stop matching what it returns.
    """
    return UsageAnalyticsResponse.of(await use_case.execute_own(actor, window=window))
