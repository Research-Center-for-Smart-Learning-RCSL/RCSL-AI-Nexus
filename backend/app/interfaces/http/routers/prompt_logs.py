"""The §9.2 transcripts, read-only, on the admin entrances only.

Two routes, and the difference between them is the point rather than a REST
convention. `GET /prompt-logs` lists what was captured and discloses no message
content. `GET /prompt-logs/{id}` returns one conversation in full and writes an
audit row naming it. An operator who never opens a transcript leaves no
disclosure record because there was no disclosure.

**Not mounted on the gateway**, like `assistant` and unlike `chat`. The gateway
writes to this table and cannot read it — its database account has `SELECT`
revoked on `prompt_logs` specifically (`db_roles.py`) — so a route here would be
refused by Postgres rather than by routing. Both controls are wanted: the
mounting is the intent and the grant is what holds if the intent is edited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.application.use_cases.read_prompt_logs import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ReadPromptLogs,
)
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_prompt_logs
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    PromptLogListResponse,
    PromptLogTranscriptResponse,
)

router = APIRouter(tags=["prompt-logs"])


@router.get("/prompt-logs")
async def list_prompt_logs(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadPromptLogs, Depends(build_read_prompt_logs)],
    actor_id: Annotated[str | None, Query(max_length=36)] = None,
    api_key_id: Annotated[str | None, Query(max_length=64)] = None,
    capability: Annotated[str | None, Query(max_length=64)] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    # Declared, because the repository filters on them and nothing was passing
    # them: `since`/`until` were plumbed through the port, the use case and the
    # `WHERE` clause while no caller could ever set either, so the two `at`
    # comparisons were unreachable and "what did this key send yesterday
    # afternoon" meant paging by hand. Dead plumbing reads as a working filter
    # to anyone looking at the query and not the router.
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptLogListResponse:
    page = await use_case.list_page(
        actor,
        actor_id=actor_id,
        api_key_id=api_key_id,
        capability=capability,
        # The filter that matters most in practice. A caller reports a failure
        # by quoting the request id from their error envelope, and this turns
        # that string into the conversation it names.
        request_id=request_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return PromptLogListResponse.of(page)


@router.get("/prompt-logs/{entry_id}")
async def read_prompt_log(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadPromptLogs, Depends(build_read_prompt_logs)],
    entry_id: Annotated[str, Path(max_length=36)],
) -> PromptLogTranscriptResponse:
    """The audited one. See `ReadPromptLogs.read_transcript`."""
    return PromptLogTranscriptResponse.of(await use_case.read_transcript(actor, entry_id))
