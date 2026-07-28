"""What somebody needs in order to call the inference API.

The management UI issues a key and then has to tell the holder where to send
it. That answer lives on the *admin* origin while the endpoint it describes is
on another host, so nothing about the incoming request can supply it; it comes
from configuration.

Served here rather than added to `GET /me`, which answers who the caller is.
This answers where the platform is, and the two change for different reasons.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.domain.entities.actor import Actor
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import ListCapabilitiesDep
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import GatewayInfoResponse

router = APIRouter(prefix="/gateway", tags=["gateway"])


@router.get("")
async def read_gateway_info(
    actor: Annotated[Actor, Depends(current_actor)],
    capabilities: ListCapabilitiesDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GatewayInfoResponse:
    """Reachable by a member, not only an administrator.

    Members are exactly the people this is for: §5.2 grants them their own API
    keys, and a key with no endpoint to send it to is not a working key. The
    underlying use case requires `chat:use`, which is the scope for reaching
    inference at all, so the audience is precisely those who can use what it
    describes.
    """
    return GatewayInfoResponse(
        base_url=settings.gateway_base_url,
        capabilities=await capabilities.execute(actor),
    )
