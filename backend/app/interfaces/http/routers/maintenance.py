"""The maintenance hold (#61).

`GET /maintenance/status` is the one route here with no caller: the
maintenance page polls it, for visitors and for accounts the hold has just
signed out, so it must answer when nobody is signed in and must say nothing a
visitor should not learn. Everything else is for platform administrators.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.manage_maintenance import ManageMaintenance
from app.domain.entities.actor import Actor
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_manage_maintenance
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    EnterMaintenanceRequest,
    MaintenanceMessageRequest,
    MaintenanceStatusResponse,
    PublicMaintenanceStatusResponse,
)

router = APIRouter(prefix="/maintenance", tags=["maintenance"])

ManageDep = Annotated[ManageMaintenance, Depends(build_manage_maintenance)]
ActorDep = Annotated[Actor, Depends(current_actor)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/status")
async def public_maintenance_status(maintenance: ManageDep) -> PublicMaintenanceStatusResponse:
    return PublicMaintenanceStatusResponse.of(await maintenance.public_status())


@router.get("")
async def maintenance_status(
    actor: ActorDep, maintenance: ManageDep, settings: SettingsDep
) -> MaintenanceStatusResponse:
    state = await maintenance.status(actor)
    return MaintenanceStatusResponse.of(state, enabled=settings.maintenance_enabled)


@router.post("/enter")
async def enter_maintenance(
    payload: EnterMaintenanceRequest,
    actor: ActorDep,
    maintenance: ManageDep,
    settings: SettingsDep,
) -> MaintenanceStatusResponse:
    """Closes every entrance to everyone but platform administrators and signs
    every other local account out, immediately. Pressing it again while the
    platform is closed changes nothing and returns the current state."""
    state = await maintenance.enter(
        actor, message=payload.message, expected_return_at=payload.expected_return_at
    )
    return MaintenanceStatusResponse.of(state, enabled=settings.maintenance_enabled)


@router.post("/reopen")
async def reopen_after_maintenance(
    actor: ActorDep, maintenance: ManageDep, settings: SettingsDep
) -> MaintenanceStatusResponse:
    """Reopens every entrance. Accounts the hold signed out sign in again;
    API keys work again unchanged."""
    state = await maintenance.reopen(actor)
    return MaintenanceStatusResponse.of(state, enabled=settings.maintenance_enabled)


@router.put("/message")
async def set_maintenance_message(
    payload: MaintenanceMessageRequest,
    actor: ActorDep,
    maintenance: ManageDep,
    settings: SettingsDep,
) -> MaintenanceStatusResponse:
    state = await maintenance.set_message(
        actor,
        message=payload.message,
        expected_return_at=payload.expected_return_at,
        expected_revision=payload.expected_revision,
    )
    return MaintenanceStatusResponse.of(state, enabled=settings.maintenance_enabled)
