"""HTTP enforcement boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address

from app.adapters.persistence.repositories import (
    PostgresUsageRepository,
)
from app.domain.entities.api_key import ApiKey
from app.domain.exceptions import NotAuthenticatedError, QuotaExceededError, RateLimitedError
from app.domain.ports.infrastructure_ports import CachePort


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
