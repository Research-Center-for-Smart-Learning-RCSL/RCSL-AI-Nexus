"""Management-only routing status, without model aliases or runtime calls."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.domain.entities.actor import Actor, Scope
from app.infrastructure.availability import read_availability
from app.infrastructure.di.shared import SessionDep
from app.interfaces.http.middleware.identity import current_actor

router = APIRouter(prefix="/capabilities", tags=["routing"])


class CapabilityStatus(BaseModel):
    capability: str
    enabled: bool
    available: bool
    reasons: list[str]


class AvailabilityResponse(BaseModel):
    observed_at: datetime
    capabilities: list[CapabilityStatus]


@router.get("/availability")
async def availability(
    request: Request,
    session: SessionDep,
    actor: Annotated[Actor, Depends(current_actor)],
) -> AvailabilityResponse:
    request.app.state.authz.require(actor, Scope.ROUTING_READ)
    snapshot = await read_availability(session, request.app.state.runtimes)
    return AvailabilityResponse(
        observed_at=snapshot.at,
        capabilities=[
            CapabilityStatus(
                capability=c.capability,
                enabled=c.enabled,
                available=c.available,
                reasons=list(c.reasons),
            )
            for c in snapshot.capabilities
        ],
    )
