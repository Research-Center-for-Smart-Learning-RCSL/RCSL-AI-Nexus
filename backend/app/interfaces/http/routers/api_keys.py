"""API key issuance and revocation.

The plaintext appears in the response to `POST /api-keys` and nowhere else.
`ApiKeyResponse` has no field for the digest either, so a response model that
cannot express the secret cannot leak it by a future edit.

Owner display names are resolved here rather than in the use case: they are a
presentation concern, and joining them into the domain would put a users
lookup inside key handling for the sake of a table column.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.adapters.persistence.repositories import PostgresUserRepository
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_manage_api_keys, get_user_repository
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    IssuedApiKeyResponse,
    UpdateApiKeyRequest,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("")
async def list_api_keys(
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
    users: Annotated[PostgresUserRepository, Depends(get_user_repository)],
) -> list[ApiKeyResponse]:
    visible, last_used = await keys.list_visible(actor)

    # One listing rather than a lookup per key. The table is small, and a
    # per-row query here would be N+1 on the page that is most often open.
    display = {u.id: u.display_name for u in await users.list_all()}

    return [
        ApiKeyResponse.of(
            key,
            owner_display=display.get(key.owner_id),
            last_used_at=last_used.get(key.key_id),
        )
        for key in visible
    ]


@router.post("", status_code=201)
async def create_api_key(
    payload: CreateApiKeyRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
) -> IssuedApiKeyResponse:
    issued = await keys.create(
        actor,
        name=payload.name,
        owner_id=payload.owner_id,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
        rate_limit_rpm=payload.rate_limit_rpm,
        # Zero means "no quota" on the wire, because the form has no way to
        # express absence. The entity uses None for that.
        quota_tokens_per_day=payload.quota_tokens_per_day or None,
        allowed_cidrs=payload.allowed_cidrs,
    )
    return IssuedApiKeyResponse(key=ApiKeyResponse.of(issued.key), plaintext=issued.plaintext)


@router.patch("/{key_id}")
async def update_api_key(
    key_id: str,
    payload: UpdateApiKeyRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
) -> ApiKeyResponse:
    key = await keys.update(
        actor,
        key_id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
        rate_limit_rpm=payload.rate_limit_rpm,
        quota_tokens_per_day=payload.quota_tokens_per_day,
        allowed_cidrs=payload.allowed_cidrs,
    )
    return ApiKeyResponse.of(key)


@router.post("/{key_id}/revoke", status_code=204)
async def revoke_api_key(
    key_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
) -> Response:
    """Immediate. The gateway checks `revoked_at` on every request rather than
    caching a decision, so there is no window in which a revoked key still
    works."""
    await keys.revoke(actor, key_id)
    return Response(status_code=204)
