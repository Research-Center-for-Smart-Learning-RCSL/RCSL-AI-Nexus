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
from app.domain.entities.capability import ISSUABLE_CAPABILITIES
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
from app.interfaces.http.request_actor import remember_actor
from app.interfaces.http.request_context import grant_debug_detail

BEARER = "bearer "


def _scopes_for(key: ApiKey) -> frozenset[Scope]:
    """Map the key's stored capability names onto scopes.

    Every inference capability grants the same scope, because there is one
    inference use case and `CHAT_USE` is the permission to reach it. Which
    capability was actually asked for is enforced separately, against
    `Actor.allowed_capabilities`.

    Still a fixed rule rather than a lookup: the stored list can only narrow
    what a key of this kind may ever hold, so a compromised database row cannot
    promote a key into the control plane. What it can no longer do is disagree
    about which names exist. An explicit table here listed only `chat`, which
    made a key issued for any of the other four powerless while the form
    offering the choice presented it as meaningful; a table whose values were
    then all identical would have carried no information and reintroduced that
    bug the next time a capability was added.
    """
    scopes = {Scope.CHAT_USE for c in key.scopes if c in ISSUABLE_CAPABILITIES}
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


async def _assert_within_quota(key: ApiKey, usage: PostgresUsageRepository) -> None:
    """Rolling 24-hour token budget, both halves of the work counted.

    The window trails the current moment rather than resetting at midnight, so
    a caller that exhausts it is not waiting for a date to change; it is
    waiting for its own past requests to age out one by one. That distinction
    is invisible from outside, which is why the refusal carries the wait rather
    than leaving the caller to infer it from the field's name.
    """
    if key.quota_tokens_per_day is None:
        return

    used = await usage.tokens_used_today(key.key_id)
    if used < key.quota_tokens_per_day:
        return

    # One token of headroom is enough to be admitted, hence the `+ 1`: the
    # check above refuses on `>=`, so releasing exactly the overshoot would
    # land back on the boundary and refuse again.
    recovers_at = await usage.quota_recovers_at(
        key.key_id, tokens_to_release=used - key.quota_tokens_per_day + 1
    )
    wait = None
    if recovers_at is not None:
        wait = max(1, int((recovers_at - datetime.now(UTC)).total_seconds()))

    raise QuotaExceededError(
        detail=f"key {key.key_id} used {used} of {key.quota_tokens_per_day}",
        retry_after_seconds=wait,
    )


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


def _actor_for_key(key: ApiKey) -> Actor:
    """What an API key is, as an actor. Built here rather than inline so the
    request can remember it before the checks that may refuse it."""
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
        #
        # Intersected rather than passed through, for the same reason
        # `_scopes_for` is a fixed rule: a stored list may narrow what a key
        # reaches and must never widen it. `ManageApiKeys` already refuses to
        # issue a routable-only capability, so this only matters for a row that
        # did not come from it — but that row is exactly the threat the rule
        # exists for, and without the intersection a single direct database
        # write would let a gateway key reach `assist`, which serves the
        # management assistant.
        allowed_capabilities=key.scopes & ISSUABLE_CAPABILITIES,
        # This key's declared substitute for a capability it was not issued
        # for, or None to refuse — which is what every key without one does.
        # Passed through rather than intersected, because `Actor.capability_for`
        # re-checks it against the set above and a value outside it therefore
        # decides nothing. The one rule, in the one place that reads it.
        default_capability=key.default_capability,
        # The key-side debug window, carried onto the actor so the application
        # layer can read it. `grant_debug_detail` above sets the same value
        # into a contextvar for the error envelope; `RouteChatRequest` decides
        # full prompt logging from this one, because it sits two layers away
        # from the contextvar and reaching for it there would invert the
        # dependency the hexagon exists to hold. See §9.2.
        debug_logging_until=key.debug_logging_until,
    )


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
