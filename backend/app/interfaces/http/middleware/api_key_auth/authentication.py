"""HTTP authentication boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresUsageRepository,
)
from app.domain.entities.actor import Actor
from app.domain.exceptions import NotAuthenticatedError
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.services.api_key_service import ApiKeyService
from app.infrastructure.di import (
    get_api_key_repository,
    get_api_key_service,
    get_cache,
    get_usage_repository,
)
from app.interfaces.http.middleware.client_ip import resolve_client_ip
from app.interfaces.http.request_actor import remember_actor
from app.interfaces.http.request_context import grant_debug_detail

from .enforcement import _assert_source_allowed, _assert_within_quota, _assert_within_rate_limit
from .resolution import _actor_for_key

BEARER = "bearer "


async def _authenticate(
    request: Request,
    service: ApiKeyService,
    keys: PostgresApiKeyRepository,
    usage: PostgresUsageRepository,
    cache: CachePort,
    *,
    enforce_quota: bool,
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

    # As soon as the credential is known, before the checks below: the debug
    # window exists precisely so that a CIDR, rate-limit or quota refusal can
    # explain itself to the caller being debugged. See request_context.
    grant_debug_detail(key.debug_logging_until)

    # Left on the request here, for the same reason and at the same moment.
    # The exception handler runs after this frame is gone and still has to say
    # who was refused, and on the gateway that is the whole of `refusals` —
    # every caller here is an API key.
    #
    # **Before the four checks below, not after them.** Remembering it at the
    # `return` stored the 413s and dropped everything those checks raise: a
    # rate limit, an exhausted quota, a blocked country, a source outside the
    # key's allowlist. All four are refusals of a caller who is fully
    # identified — the key is in hand two lines above — and a `429` that cannot
    # be looked up is exactly the row `retry_after_seconds` was added for,
    # since the header carrying it is gone by the time anybody reads back.
    #
    # **Missing entirely until 2026-08-18, and invisible while it was.** The
    # only consumer of `actor_from_request` was `_audit_refusal`, which returns
    # early on the gateway because that application deliberately has no `audit`
    # on its state (security.md 12). So the one resolver that never remembered
    # its actor was the one whose omission nothing could observe, until a
    # deployed 413 — the refusal this table was built for — was answered
    # correctly and stored nowhere. Found by provoking one against the running
    # gateway, not by a test.
    actor = remember_actor(request, _actor_for_key(key))

    # Evaluated unconditionally, and deliberately not folded into the branch
    # below. Making this conditional on `key.allowed_cidrs` reads as an obvious
    # optimisation and would stop the proxy-secret check running at all.
    client_ip = resolve_client_ip(request)
    request.app.state.geo_filter.assert_allowed(client_ip)
    _assert_source_allowed(key, client_ip)

    await _assert_within_rate_limit(key, cache)

    if enforce_quota:
        await _assert_within_quota(key, usage)

    return actor


async def authenticate_api_key(
    request: Request,
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    keys: Annotated[PostgresApiKeyRepository, Depends(get_api_key_repository)],
    usage: Annotated[PostgresUsageRepository, Depends(get_usage_repository)],
    cache: Annotated[CachePort, Depends(get_cache)],
) -> Actor:
    """Every check, for every endpoint that spends the hardware."""
    return await _authenticate(request, service, keys, usage, cache, enforce_quota=True)


async def authenticate_api_key_without_quota(
    request: Request,
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    keys: Annotated[PostgresApiKeyRepository, Depends(get_api_key_repository)],
    usage: Annotated[PostgresUsageRepository, Depends(get_usage_repository)],
    cache: Annotated[CachePort, Depends(get_cache)],
) -> Actor:
    """The same checks minus the token budget, for endpoints that spend none.

    A token quota is a limit on inference, and applying it to a call that runs
    no model refuses a request whose cost is a database read. The harm is not
    the refusal itself but where it lands: every OpenAI-compatible client asks
    for the model list at startup, so an exhausted quota stopped an agent from
    starting rather than from generating, and the operator saw a client that
    could not connect instead of a key that had run out.

    Everything that protects the platform still runs — the key must be valid,
    active, within its per-minute rate limit, and from a permitted address and
    country. Only the budget that this call cannot consume is skipped.
    """
    return await _authenticate(request, service, keys, usage, cache, enforce_quota=False)
