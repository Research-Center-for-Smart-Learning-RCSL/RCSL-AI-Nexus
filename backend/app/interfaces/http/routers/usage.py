"""Usage, aggregated for the charts and listed row by row.

Three endpoints and two shapes. `/usage` is the tenant's aggregate figures
behind `usage:read_all`, the same scope the dashboard totals use, and
`/usage/me` is the caller's own behind `usage:read_own`, which every human role
holds and nothing required until 2026-08-04. They are separate paths rather than
one that quietly returns less to a narrower caller: a chart that silently
changes what it counts based on who is looking is one nobody can compare with
anyone else's.

`/usage/records` is the other shape, added 2026-09-07, and it takes the opposite
approach on purpose — one path whose rows are narrowed inside the use case. A
chart is a claim about a population, so who it counts has to be in its name; a
row is the same object whoever reads it, and the reader who may see only their
own still wants the filters to work. `read_refusals.py` settled that argument
first and this follows it.

The listing exists because compaction gave the platform something to record per
request and no way to show it. `usage_records` had been written since the first
migration with every reader an aggregate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.use_cases.read_usage_analytics import ReadUsageAnalytics, UsageWindow
from app.application.use_cases.read_usage_records import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ReadUsageRecords,
)
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_usage_analytics, build_read_usage_records
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    UsageAnalyticsResponse,
    UsageRecordListResponse,
)

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
@router.get("/usage/records")
async def list_usage_records(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadUsageRecords, Depends(build_read_usage_records)],
    actor_id: Annotated[str | None, Query(max_length=36)] = None,
    api_key_id: Annotated[str | None, Query(max_length=64)] = None,
    capability: Annotated[str | None, Query(max_length=64)] = None,
    compacted: Annotated[bool | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UsageRecordListResponse:
    """The individual requests behind the charts above.

    One route rather than the `/usage` and `/usage/me` pair beside it, and the
    difference is deliberate. Those two are separate because they check
    different scopes and return the tenant's figures or yours, and a boolean
    argument would put that decision at the call site. Here the rows are the
    same object whoever reads them, so the narrowing is a filter the use case
    applies — the shape `read_refusals.py` settled on for exactly this question.

    `compacted=true` is the filter the disclosure requirement wanted: it is how
    an operator answers "which requests did this platform reduce, and whose".
    """
    page = await use_case.list_page(
        actor,
        actor_id=actor_id,
        api_key_id=api_key_id,
        capability=capability,
        compacted=compacted,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return UsageRecordListResponse.of(page)


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
