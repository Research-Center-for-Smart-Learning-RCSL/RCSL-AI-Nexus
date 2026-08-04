"""The two read paths behind the logs and usage-analytics screens.

Both are admin-only, and both fold or page data the UI cannot be trusted to bound
itself, so the authorization, the limit clamp, and the aggregation are pinned
here. The repositories' SQL (date_trunc bucketing, the filtered query) is left to
integration against real Postgres; these cover the use-case logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.read_audit_log import MAX_LIMIT, ReadAuditLog
from app.application.use_cases.read_usage_analytics import ReadUsageAnalytics
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditEntry
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import NotAuthorizedError
from tests.unit.fakes import FakeUsage

_AUTHZ = RoleAuthorization()


def _actor(*scopes: Scope, who: str = "a1") -> Actor:
    return Actor(
        id=who,
        display="admin@x",
        role=Role.ADMIN,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t1",
    )


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeAuditLog:
    """Captures the filters and paging it was called with, so the use case's
    clamp and passthrough are observable."""

    def __init__(self, entries: list[AuditEntry], total: int) -> None:
        self._entries = entries
        self._total = total
        self.list_kwargs: dict[str, object] = {}
        self.count_kwargs: dict[str, object] = {}

    async def list_entries(self, **kwargs: object) -> list[AuditEntry]:
        self.list_kwargs = kwargs
        return self._entries

    async def count_entries(self, **kwargs: object) -> int:
        self.count_kwargs = kwargs
        return self._total


def _entry(action: str) -> AuditEntry:
    return AuditEntry(
        id="e1",
        actor_id="a1",
        actor_display="admin@x",
        actor_source="local",
        action=action,
        target=None,
        outcome="success",
        detail={"k": "v"},
        at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        tenant_id="t1",
    )


# --- audit log -----------------------------------------------------------


async def test_reading_the_log_needs_logs_read() -> None:
    use_case = ReadAuditLog(FakeAuditLog([], 0), _AUTHZ)
    with pytest.raises(NotAuthorizedError):
        await use_case.execute(_actor(Scope.USER_READ))


async def test_the_log_page_carries_entries_and_the_total() -> None:
    repo = FakeAuditLog([_entry("user.invited")], total=42)
    use_case = ReadAuditLog(repo, _AUTHZ)

    page = await use_case.execute(_actor(Scope.LOGS_READ), action="user.invited")

    assert [e.action for e in page.entries] == ["user.invited"]
    assert page.total == 42
    # The filter reaches both queries, so the count matches the page.
    assert repo.list_kwargs["action"] == "user.invited"
    assert repo.count_kwargs["action"] == "user.invited"


async def test_an_oversized_limit_is_clamped() -> None:
    repo = FakeAuditLog([], 0)
    use_case = ReadAuditLog(repo, _AUTHZ)

    page = await use_case.execute(_actor(Scope.LOGS_READ), limit=10_000, offset=-5)

    assert page.limit == MAX_LIMIT
    assert page.offset == 0
    assert repo.list_kwargs["limit"] == MAX_LIMIT
    assert repo.list_kwargs["offset"] == 0


# --- usage analytics -----------------------------------------------------


async def test_reading_usage_needs_usage_read_all() -> None:
    use_case = ReadUsageAnalytics(FakeUsage(), _AUTHZ, FakeClock(datetime.now(UTC)))
    with pytest.raises(NotAuthorizedError):
        await use_case.execute(_actor(Scope.USAGE_READ_OWN))


async def test_usage_folds_into_totals_and_per_capability_series() -> None:
    now = datetime(2026, 7, 25, 12, 30, tzinfo=UTC)
    usage = FakeUsage()

    def rec(cap: str, at: datetime, tokens: int) -> UsageRecord:
        return UsageRecord(
            id=f"{cap}-{at.isoformat()}",
            actor_id="a1",
            api_key_id="k1",
            capability=cap,
            model_alias="m",
            tokens=tokens,
            latency_ms=100,
            completed=True,
            at=at,
            tenant_id="t1",
        )

    usage.records = [
        rec("chat", now.replace(hour=10, minute=30), 7),
        rec("chat", now.replace(hour=11, minute=15), 10),
        rec("chat", now.replace(hour=11, minute=45), 5),
        rec("embed", now.replace(hour=11, minute=20), 3),
    ]

    result = await ReadUsageAnalytics(usage, _AUTHZ, FakeClock(now)).execute(
        _actor(Scope.USAGE_READ_ALL), window="24h"
    )

    assert result.bucket == "hour"
    assert result.until == now
    assert result.since == now - timedelta(hours=24)

    # Totals fold across capabilities, ordered by time.
    totals = [(p.at.hour, p.requests, p.tokens) for p in result.totals]
    assert totals == [(10, 1, 7), (11, 3, 18)]

    # Per-capability series, ordered by capability name.
    by_cap = {
        s.capability: [(p.at.hour, p.requests, p.tokens) for p in s.points]
        for s in result.by_capability
    }
    assert by_cap == {
        "chat": [(10, 1, 7), (11, 2, 15)],
        "embed": [(11, 1, 3)],
    }


async def test_a_window_with_no_traffic_is_empty_not_an_error() -> None:
    result = await ReadUsageAnalytics(FakeUsage(), _AUTHZ, FakeClock(datetime.now(UTC))).execute(
        _actor(Scope.USAGE_READ_ALL), window="7d"
    )
    assert result.bucket == "day"
    assert result.totals == []
    assert result.by_capability == []


# --- own usage -----------------------------------------------------------
#
# `usage:read_own` was granted to every human role from the beginning and
# required by nothing until 2026-08-04, so a member held a permission with
# nowhere to spend it. These cover the two halves of closing that: the narrower
# scope opens the narrower read, and the narrower read is actually narrower.


def _usage_across_two_accounts(now: datetime) -> FakeUsage:
    usage = FakeUsage()

    def rec(actor_id: str, at: datetime, tokens: int) -> UsageRecord:
        return UsageRecord(
            id=f"{actor_id}-{at.isoformat()}",
            actor_id=actor_id,
            api_key_id="k1",
            capability="chat",
            model_alias="m",
            tokens=tokens,
            latency_ms=100,
            completed=True,
            at=at,
            tenant_id="t1",
        )

    usage.records = [
        rec("mine", now.replace(hour=10, minute=0), 7),
        rec("theirs", now.replace(hour=10, minute=30), 100),
        rec("mine", now.replace(hour=11, minute=0), 5),
    ]
    return usage


async def test_own_usage_needs_only_the_narrow_scope() -> None:
    """The point of the endpoint: a member with no sight of the tenant's figures
    can still see their own. `execute` refuses the same actor, which is what
    makes the two scopes worth having separately."""
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    use_case = ReadUsageAnalytics(_usage_across_two_accounts(now), _AUTHZ, FakeClock(now))
    member = _actor(Scope.USAGE_READ_OWN, who="mine")

    result = await use_case.execute_own(member, window="24h")
    assert [(p.at.hour, p.requests, p.tokens) for p in result.totals] == [(10, 1, 7), (11, 1, 5)]

    with pytest.raises(NotAuthorizedError):
        await use_case.execute(member, window="24h")


async def test_own_usage_excludes_everybody_elses() -> None:
    """The assertion that would fail if the filter were dropped: the other
    account's single 100-token row is the loudest in the window, so a result
    that included it could not be mistaken for a correct one."""
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    usage = _usage_across_two_accounts(now)
    use_case = ReadUsageAnalytics(usage, _AUTHZ, FakeClock(now))

    mine = await use_case.execute_own(_actor(Scope.USAGE_READ_OWN, who="mine"), window="24h")
    everyone = await use_case.execute(_actor(Scope.USAGE_READ_ALL), window="24h")

    assert sum(p.tokens for p in mine.totals) == 12
    assert sum(p.tokens for p in everyone.totals) == 112


async def test_an_account_with_no_traffic_of_its_own_sees_an_empty_chart() -> None:
    """Not an error and not the tenant's figures, which is the failure mode a
    filter applied with `or` rather than `and` would produce."""
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    use_case = ReadUsageAnalytics(_usage_across_two_accounts(now), _AUTHZ, FakeClock(now))

    result = await use_case.execute_own(
        _actor(Scope.USAGE_READ_OWN, who="someone-else"), window="24h"
    )

    assert result.totals == []
    assert result.by_capability == []
