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
from app.application.use_cases.reset_node_runtime import ResetNodeRuntime
from app.domain.entities.actor import Actor
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_manage_maintenance, build_reset_node_runtime
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    EnterMaintenanceRequest,
    MaintenanceMessageRequest,
    MaintenanceStatusResponse,
    PublicMaintenanceStatusResponse,
    RuntimeResetRequest,
    RuntimeResetResponse,
    UnknownOperationsResponse,
    UnknownOperationView,
)

router = APIRouter(prefix="/maintenance", tags=["maintenance"])

ManageDep = Annotated[ManageMaintenance, Depends(build_manage_maintenance)]
ResetDep = Annotated[ResetNodeRuntime, Depends(build_reset_node_runtime)]
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
    return MaintenanceStatusResponse.of(
        state, enabled=settings.maintenance_enabled, operation=await maintenance.operation(actor)
    )


@router.post("/enter")
async def enter_maintenance(
    payload: EnterMaintenanceRequest,
    actor: ActorDep,
    maintenance: ManageDep,
    settings: SettingsDep,
) -> MaintenanceStatusResponse:
    """Closes every entrance to everyone but platform administrators and signs
    every other local account out, immediately, and records the entry the
    maintenance coordinator then carries out on every node. Pressing it again
    while the platform is closed changes nothing and returns the current
    state."""
    state = await maintenance.enter(
        actor, message=payload.message, expected_return_at=payload.expected_return_at
    )
    return MaintenanceStatusResponse.of(
        state, enabled=settings.maintenance_enabled, operation=await maintenance.operation(actor)
    )


@router.post("/restore")
async def restore_after_maintenance(
    actor: ActorDep, maintenance: ManageDep, settings: SettingsDep
) -> MaintenanceStatusResponse:
    """Loads back every model the entry released, on the node it was on, with
    the weights and context it had, checks each one answers, and reopens the
    platform only once every node verifies. Until then the platform stays
    closed; a failure keeps it closed and can be retried. Pressing it again
    while a restore runs returns that restore."""
    operation = await maintenance.restore(actor)
    state = await maintenance.status(actor)
    return MaintenanceStatusResponse.of(
        state, enabled=settings.maintenance_enabled, operation=operation
    )


@router.post("/retry")
async def retry_maintenance_entry(
    actor: ActorDep, maintenance: ManageDep, settings: SettingsDep
) -> MaintenanceStatusResponse:
    """Runs a failed entry's or restore's failed nodes again from the phase
    each reached. The snapshot each node saved is kept; the platform stays
    closed."""
    operation = await maintenance.retry(actor)
    state = await maintenance.status(actor)
    return MaintenanceStatusResponse.of(
        state, enabled=settings.maintenance_enabled, operation=operation
    )


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


@router.get("/unknown-operations")
async def unknown_operations(actor: ActorDep, resets: ResetDep) -> UnknownOperationsResponse:
    """Operations each node sent and cannot account for. Each blocks its node
    until a supervised reset proves the runtime that may have them gone."""
    return UnknownOperationsResponse(
        operations=[
            UnknownOperationView(
                node_id=u.node_id,
                op_id=u.op_id,
                kind=u.kind,
                reason=u.reason,
                submitted_at=u.submitted_at,
            )
            for u in await resets.list(actor)
        ],
        reset_available=resets.available,
    )


@router.post("/resets")
async def reset_runtime(
    payload: RuntimeResetRequest, actor: ActorDep, resets: ResetDep
) -> RuntimeResetResponse:
    """Restart the node's runtime under witness evidence and clear the
    operation. Answered with what the agent said, cleared or not: a refusal
    (no witness, the supervisor failed) is the administrator's to read, not an
    error page. The restart unloads every model on the node; the residency
    reconciler loads the resident set back."""
    outcome = await resets.reset(
        actor, node_id=payload.node_id, op_id=payload.op_id, evidence=payload.evidence.strip()
    )
    return RuntimeResetResponse(
        node_id=outcome.node_id, op_id=outcome.op_id, cleared=outcome.cleared, detail=outcome.detail
    )
