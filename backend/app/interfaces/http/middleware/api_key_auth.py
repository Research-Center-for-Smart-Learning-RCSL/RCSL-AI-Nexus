"""API key authentication for the gateway.

Produces an `Actor` so that use cases see one shape regardless of how the
caller authenticated. Every rejection here raises the same error with the same
public message; distinguishing "no such key" from "wrong key" from "expired"
would tell an attacker which of those to fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated

from fastapi import Depends, Request

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresUsageRepository,
)
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.exceptions import NotAuthenticatedError, QuotaExceededError, RateLimitedError
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.di import (
    get_api_key_repository,
    get_api_key_service,
    get_cache,
    get_usage_repository,
)
from app.interfaces.http.middleware.client_ip import resolve_client_ip

BEARER = "bearer "

_CAPABILITY_SCOPES: dict[str, Scope] = {
    "chat": Scope.CHAT_USE,
    "code": Scope.CHAT_USE,
    "vision": Scope.CHAT_USE,
    "embedding": Scope.CHAT_USE,
    "rerank": Scope.CHAT_USE,
}
"""Every inference capability grants the same scope, because there is one
inference use case and `CHAT_USE` is the permission to reach it.

Only `chat` was listed before, which made the other four inert: a key issued
for `code` alone mapped to no scopes at all and was refused every request,
while the form that issued it presented the choice as meaningful. The
capability actually asked for is enforced separately, from
`Actor.allowed_capabilities`.
"""


def _scopes_for(key: ApiKey) -> frozenset[Scope]:
    """Map the key's stored capability names onto scopes.

    A hardcoded mapping, not a lookup: a compromised database row must not be
    able to promote a key into the control plane. The stored list can only
    narrow what a key of this kind may ever hold.
    """
    scopes = {_CAPABILITY_SCOPES[c] for c in key.scopes if c in _CAPABILITY_SCOPES}
    if scopes:
        # Reading your own usage is implied by being able to consume anything.
        # Granted with the first real scope rather than unconditionally, so a
        # key issued with none stays genuinely powerless.
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


async def _assert_within_rate_limit(key: ApiKey, cache: CachePort) -> None:
    """Fixed-window per-key request limit.

    A fixed window admits up to twice the nominal rate across a boundary. That
    is accepted: the purpose is to stop one key monopolising the hardware, and
    the concurrency semaphore bounds the instantaneous damage regardless.
    """
    if key.rate_limit_rpm <= 0:
        return
    window = int(datetime.now(UTC).timestamp()) // 60
    count = await cache.incr(f"ratelimit:{key.key_id}:{window}", ttl_seconds=120)
    if count > key.rate_limit_rpm:
        raise RateLimitedError(retry_after_seconds=60)


async def authenticate_api_key(
    request: Request,
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    keys: Annotated[PostgresApiKeyRepository, Depends(get_api_key_repository)],
    usage: Annotated[PostgresUsageRepository, Depends(get_usage_repository)],
    cache: Annotated[CachePort, Depends(get_cache)],
) -> Actor:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER):
        raise NotAuthenticatedError(detail="missing bearer token")

    plaintext = header[len(BEARER) :].strip()

    key_id = service.parse_key_id(plaintext)
    if key_id is None:
        raise NotAuthenticatedError(detail="malformed token")

    key = await keys.get_by_key_id(key_id)
    if key is None or not service.verify(plaintext, key.digest):
        raise NotAuthenticatedError(detail=f"unknown or mismatched key {key_id}")

    now = datetime.now(UTC)
    if not key.is_active(now):
        raise NotAuthenticatedError(detail=f"inactive key {key_id}")

    # Evaluated unconditionally, and deliberately not folded into the branch
    # below. Making this conditional on `key.allowed_cidrs` reads as an obvious
    # optimisation and would stop the proxy-secret check running at all.
    client_ip = resolve_client_ip(request)
    request.app.state.geo_filter.assert_allowed(client_ip)
    _assert_source_allowed(key, client_ip)

    await _assert_within_rate_limit(key, cache)

    if key.quota_tokens_per_day is not None:
        used = await usage.tokens_used_today(key.key_id)
        if used >= key.quota_tokens_per_day:
            raise QuotaExceededError(detail=f"key {key_id} used {used}")

    return Actor(
        id=key.owner_id,
        display=key.key_id,
        role=Role.SERVICE,
        source="api_key",
        scopes=_scopes_for(key),
        api_key_id=key.key_id,
        # The key's tenant, so usage is attributed to it and, once the knowledge
        # base exists, a key can only ever reach its own tenant's data.
        tenant_id=key.tenant_id,
        # What the key was issued for, checked against the capability each
        # request names. Without it the list was decorative: any valid key
        # reached every capability the deployment could route.
        allowed_capabilities=key.scopes,
    )
