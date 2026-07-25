"""The audit log, read-only.

Admin-only, through `logs:read` on the use case. The write side records every
administrative action already; this surfaces it, filtered and paged.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.use_cases.read_audit_log import DEFAULT_LIMIT, MAX_LIMIT, ReadAuditLog
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_audit_log
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import AuditLogResponse

router = APIRouter(tags=["logs"])


@router.get("/logs")
async def read_logs(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadAuditLog, Depends(build_read_audit_log)],
    action: Annotated[str | None, Query(max_length=64)] = None,
    outcome: Annotated[str | None, Query(max_length=16)] = None,
    actor_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogResponse:
    page = await use_case.execute(
        actor,
        action=action,
        outcome=outcome,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    return AuditLogResponse.of(page)
