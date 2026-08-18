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
from app.application.use_cases.manage_api_keys import UNCHANGED, ManageApiKeys
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_manage_api_keys, get_user_repository_scoped
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    IssuedApiKeyResponse,
    SetDebugWindowRequest,
    UpdateApiKeyRequest,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("")
async def list_api_keys(
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
    users: Annotated[PostgresUserRepository, Depends(get_user_repository_scoped)],
) -> list[ApiKeyResponse]:
    visible, last_used = await keys.list_visible(actor)

    # Only ids and display names, not full user entities: the latter carries
    # the password hash and TOTP secret into a handler a `user`-role caller can
    # reach. One query, not one per key. Scoped to the caller's tenant, so the
    # owner names shown are only their own tenant's.
    display = await users.display_names()

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
        # Passed through, not mapped. This previously turned `0` into `None`,
        # which the gateway reads as "no quota", while the update path stored
        # the same `0` literally and refused every request. Both values are
        # now constrained to be positive at the schema, so neither verb has a
        # special case and the field means one thing.
        quota_tokens_per_day=payload.quota_tokens_per_day,
        allowed_cidrs=payload.allowed_cidrs,
        default_capability=payload.default_capability,
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
        # Absence and null mean different things for this one field, and only
        # the request object can still tell them apart: by the time the value
        # is read they are both `None`. Omitted leaves the setting alone;
        # `"default_capability": null` clears it. See `UpdateApiKeyRequest`.
        default_capability=(
            payload.default_capability
            if "default_capability" in payload.model_fields_set
            else UNCHANGED
        ),
    )
    return ApiKeyResponse.of(key)


@router.post("/{key_id}/debug")
async def set_debug_window(
    key_id: str,
    payload: SetDebugWindowRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    keys: Annotated[ManageApiKeys, Depends(build_manage_api_keys)],
) -> ApiKeyResponse:
    """Open (or close, with 0) the time-boxed window during which error
    responses to this key carry operator-facing detail. Its own verb rather
    than a PATCH field: it changes what the platform reveals, not what the key
    may do, and the audit trail should show it as its own kind of act."""
    key = await keys.set_debug_window(actor, key_id, minutes=payload.minutes)
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
