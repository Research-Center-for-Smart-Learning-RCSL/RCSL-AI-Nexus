"""Usage over time, for the analytics charts.

Distinct from the Prometheus emission stack: that reports live operational state
to an operator over Grafana; this reads the `usage_records` accounting table, per
tenant, for the management UI. Different audience, different data, different
access path.

The window is a small closed set rather than free start/end times: the chart
offers a range picker, the bucket granularity follows from the range, and fixing
the pair keeps the query's cardinality bounded. Time comes from an injected clock
so the windowing is testable without waiting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.usage import BucketUnit
from app.domain.ports.repositories import UsageRepositoryPort
from app.domain.ports.security_ports import AuthorizationPort
from app.shared.clock import Clock

UsageWindow = Literal["24h", "7d", "30d"]

_WINDOWS: dict[UsageWindow, tuple[timedelta, BucketUnit]] = {
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
}


@dataclass(frozen=True, slots=True)
class UsagePoint:
    at: datetime
    requests: int
    tokens: int


@dataclass(frozen=True, slots=True)
class CapabilitySeries:
    capability: str
    points: list[UsagePoint]


@dataclass(frozen=True, slots=True)
class UsageAnalytics:
    bucket: BucketUnit
    since: datetime
    until: datetime
    totals: list[UsagePoint]
    by_capability: list[CapabilitySeries]


class ReadUsageAnalytics:
    def __init__(
        self,
        usage: UsageRepositoryPort,
        authz: AuthorizationPort,
        clock: Clock,
    ) -> None:
        self._usage = usage
        self._authz = authz
        self._clock = clock

    async def execute(self, actor: Actor, *, window: UsageWindow = "24h") -> UsageAnalytics:
        # The platform-wide usage scope, not usage:read_own: these are the
        # tenant's aggregate figures, the same scope the dashboard totals use.
        self._authz.require(actor, Scope.USAGE_READ_ALL)
        return await self._analytics(window, actor_id=None)

    async def execute_own(self, actor: Actor, *, window: UsageWindow = "24h") -> UsageAnalytics:
        """The same charts, narrowed to the caller's own usage.

        A separate method rather than a flag on `execute`, because the scope
        each one requires is the whole difference between them and a boolean
        argument would put that decision at the call site. `usage:read_own` is
        held by every human role — it is part of what having an account is
        worth — and until this existed nothing in the platform required it, so
        the grant named a permission with nowhere to spend it.

        Attribution is by actor rather than by key: the gateway resolves an API
        key to its owner, so this covers every key the account holds, present
        and revoked, plus its admin-chat traffic. Nobody has to remember which
        key they used.
        """
        self._authz.require(actor, Scope.USAGE_READ_OWN)
        return await self._analytics(window, actor_id=actor.id)

    async def _analytics(self, window: UsageWindow, *, actor_id: str | None) -> UsageAnalytics:
        delta, unit = _WINDOWS[window]
        until = self._clock.now()
        since = until - delta

        buckets = await self._usage.bucketed_usage(since, until, unit, actor_id=actor_id)

        # One pass folds the per-(bucket, capability) rows into per-bucket totals
        # and per-capability series. Buckets arrive ordered by time, so appending
        # preserves order within each series and in the totals.
        totals: dict[datetime, list[int]] = {}
        by_capability: dict[str, list[UsagePoint]] = {}
        for b in buckets:
            running = totals.setdefault(b.bucket_start, [0, 0])
            running[0] += b.requests
            running[1] += b.tokens
            by_capability.setdefault(b.capability, []).append(
                UsagePoint(at=b.bucket_start, requests=b.requests, tokens=b.tokens)
            )

        total_points = [
            UsagePoint(at=at, requests=r, tokens=t) for at, (r, t) in sorted(totals.items())
        ]
        series = [
            CapabilitySeries(capability=capability, points=points)
            for capability, points in sorted(by_capability.items())
        ]
        return UsageAnalytics(
            bucket=unit, since=since, until=until, totals=total_points, by_capability=series
        )
