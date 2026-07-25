"""Tenant management.

Tenants are platform-global (managed by an admin, not scoped to one tenant),
which is why this router uses `ManageTenants` directly and the use case declares
the `tenant:*` scopes. Creating a tenant returns its first administrator's
onboarding link, present in that one response and nowhere else, since only the
token's hash is stored. See docs/architecture/security.md section 7.3.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.manage_tenants import ManageTenants
from app.domain.entities.actor import Actor
from app.domain.entities.invitation import InvitationPurpose
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_manage_tenants
from app.interfaces.http.invitation_link import invitation_url
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateTenantRequest,
    CreateTenantResponse,
    InvitationResponse,
    TenantResponse,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("")
async def list_tenants(
    actor: Annotated[Actor, Depends(current_actor)],
    tenants: Annotated[ManageTenants, Depends(build_manage_tenants)],
) -> list[TenantResponse]:
    return [TenantResponse.of(t) for t in await tenants.list_all(actor)]


@router.post("", status_code=201)
async def create_tenant(
    payload: CreateTenantRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    tenants: Annotated[ManageTenants, Depends(build_manage_tenants)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateTenantResponse:
    """Creates the tenant and its first administrator's onboarding link in one
    call. The link is in this response only."""
    created = await tenants.create(
        actor,
        name=payload.name,
        first_admin_login=str(payload.first_admin_login),
        first_admin_display_name=payload.first_admin_display_name,
    )
    issued = created.invitation
    url = invitation_url(settings, InvitationPurpose.ONBOARD, issued.token)
    return CreateTenantResponse(
        tenant=TenantResponse.of(created.tenant),
        invitation=InvitationResponse(
            id=issued.invitation_id,
            user_id=issued.user.id,
            url=url,
            expires_at=issued.expires_at,
        ),
    )
