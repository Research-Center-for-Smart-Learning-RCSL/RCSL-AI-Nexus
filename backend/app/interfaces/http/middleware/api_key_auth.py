"""API key authentication for the gateway.

Produces an `Actor` so that use cases see one shape regardless of how the
caller authenticated. Every rejection here raises the same error with the same
message; distinguishing "no such key" from "wrong key" from "expired" would
tell an attacker which of those to fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated

from fastapi import Depends, Request

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.exceptions import NotAuthenticatedError, QuotaExceededError
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.di import get_api_key_repository, get_api_key_service
from app.interfaces.http.middleware.client_ip import resolve_client_ip

BEARER = "bearer "


def _scopes_for(key: ApiKey) -> frozenset[Scope]:
    """API keys carry capability names; map them onto the scope vocabulary.

    A key never receives management scopes, whatever its stored list says.
    That mapping is deliberately not data-driven: a compromised database
    should not be able to promote a key into the control plane.
    """
    scopes = {Scope.CHAT_USE} if "chat" in key.scopes else set()
    scopes.add(Scope.USAGE_READ_OWN)
    return frozenset(scopes)


def _assert_source_allowed(key: ApiKey, client_ip: IPv4Address | IPv6Address) -> None:
    """Per-key CIDR allowlist.

    Defends against key leakage specifically: a key committed to a public
    repository or spilled through a log is unusable from anywhere else. An
    empty list means unrestricted, which the issuing flow discourages.
    """
    if not key.allowed_cidrs:
        return
    if not any(client_ip in network for network in key.allowed_cidrs):
        raise NotAuthenticatedError(detail=f"source {client_ip} not permitted for {key.key_id}")


async def authenticate_api_key(
    request: Request,
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    repository=Depends(get_api_key_repository),  # noqa: B008
) -> Actor:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER):
        raise NotAuthenticatedError(detail="missing bearer token")

    plaintext = header[len(BEARER) :].strip()

    key_id = service.parse_key_id(plaintext)
    if key_id is None:
        raise NotAuthenticatedError(detail="malformed token")

    key = await repository.get_by_key_id(key_id)
    if key is None or not service.verify(plaintext, key.digest):
        raise NotAuthenticatedError(detail=f"unknown or mismatched key {key_id}")

    now = datetime.now(UTC)
    if not key.is_active(now):
        raise NotAuthenticatedError(detail=f"inactive key {key_id}")

    _assert_source_allowed(key, resolve_client_ip(request))

    if key.quota_tokens_per_day is not None:
        used = await repository_usage_today(repository, key)
        if used >= key.quota_tokens_per_day:
            raise QuotaExceededError(detail=f"key {key_id} used {used}")

    return Actor(
        id=key.owner_id,
        display=key.key_id,
        role=Role.SERVICE,
        source="api_key",
        scopes=_scopes_for(key),
    )


async def repository_usage_today(repository, key: ApiKey) -> int:
    """Indirection so the quota check can be stubbed in tests without also
    stubbing key lookup."""
    usage = getattr(repository, "tokens_used_today", None)
    if usage is None:
        return 0
    return await usage(key.key_id)
