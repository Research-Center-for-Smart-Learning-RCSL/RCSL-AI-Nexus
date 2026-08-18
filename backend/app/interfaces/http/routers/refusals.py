"""Why a caller was refused, on the admin entrances only.

One route, unlike `prompt_logs`, and the difference is the point. A transcript
is disclosed by a second, deliberate request because the list may not carry what
somebody typed; a refusal has no such second half — the row is the message the
caller already received. So there is nothing here to open.

**Not mounted on the gateway.** Its database account may `INSERT` into this
table and has `SELECT` revoked on it specifically (`db_roles.py`), so a route
here would be refused by Postgres rather than by routing. Both controls are
wanted: the mounting is the intent, the grant is what holds if the intent is
edited.

**The narrowing to "your own" is not in this file.** A caller without
`refusal:read_all` has the actor filter replaced with their own id inside the
use case, so a screen every account is expected to open keeps working rather
than answering 403 when somebody clears a filter. The response says which of the
two reads it was. `actor_display` is a search rather than a second way in: it is
ANDed with that replaced id, so it can only ever subtract from what the reader
was already allowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.use_cases.read_refusals import DEFAULT_LIMIT, MAX_LIMIT, ReadRefusals
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_refusals
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import RefusalListResponse

router = APIRouter(tags=["refusals"])


@router.get("/refusals")
async def list_refusals(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadRefusals, Depends(build_read_refusals)],
    actor_id: Annotated[str | None, Query(max_length=36)] = None,
    actor_display: Annotated[str | None, Query(max_length=200)] = None,
    api_key_id: Annotated[str | None, Query(max_length=64)] = None,
    code: Annotated[str | None, Query(max_length=64)] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RefusalListResponse:
    page = await use_case.list_page(
        actor,
        actor_id=actor_id,
        actor_display=actor_display,
        api_key_id=api_key_id,
        code=code,
        request_id=request_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return RefusalListResponse.of(page)
