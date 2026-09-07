"""The per-request usage listing, and the boundary it introduced.

`usage_records` has been written since the first migration and every reader was
an aggregate, so the table described each request and could show nobody any of
them. Making it readable is a new disclosure, not a new query: a row per request
with a timestamp is a description of how somebody works in a way that counts per
hour per capability are not. These pin the two things that follow from that —
the narrowing to your own rows, and the audit entry when somebody reaches past
it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.read_usage_records import MAX_LIMIT, ReadUsageRecords
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.usage import UsageRecord
from app.domain.exceptions import NotAuthorizedError
from tests.unit.fakes import FakeAudit, FakeUsage

_AUTHZ = RoleAuthorization()
_AT = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _actor(*scopes: Scope, who: str = "a1") -> Actor:
    return Actor(
        id=who,
        display="admin@x",
        role=Role.ADMIN,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t1",
    )


def _record(
    *,
    who: str = "a1",
    capability: str = "chat",
    tier: int | None = None,
    rid: str = "r1",
) -> UsageRecord:
    return UsageRecord(
        id=rid,
        actor_id=who,
        api_key_id="k1",
        capability=capability,
        model_alias="primary",
        tokens=10,
        prompt_tokens=100,
        latency_ms=500,
        completed=True,
        at=_AT,
        tenant_id="t1",
        compaction_tier=tier,
        tokens_before_compaction=50_000 if tier is not None else None,
        tokens_after_compaction=900 if tier is not None else None,
    )


def _build(records: list[UsageRecord]) -> tuple[ReadUsageRecords, FakeAudit]:
    usage = FakeUsage()
    usage.records.extend(records)
    audit = FakeAudit()
    return ReadUsageRecords(usage=usage, authz=_AUTHZ, audit=audit), audit


async def test_listing_requests_needs_the_narrow_scope_at_least() -> None:
    use_case, _ = _build([])
    with pytest.raises(NotAuthorizedError):
        await use_case.list_page(_actor())


async def test_a_reader_without_read_all_sees_only_their_own() -> None:
    """Overwritten rather than refused, as `read_refusals` settled: the screen's
    filters have to keep working for somebody who may only see themselves, and
    clearing a filter must not become a 403 on a page every account can open."""
    use_case, _ = _build([_record(who="a1", rid="mine"), _record(who="a2", rid="theirs")])

    page = await use_case.list_page(_actor(Scope.USAGE_READ_OWN), actor_id="a2")

    assert [e.id for e in page.entries] == ["mine"]
    assert page.scoped_to_self is True


async def test_the_narrowed_reader_is_told_that_they_were_narrowed() -> None:
    """On the response so the screen can say so. A page that quietly returns a
    subset of what its controls imply is the shape a reader mistakes for
    "there is nothing there"."""
    use_case, _ = _build([_record()])

    wide = await use_case.list_page(_actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL))

    assert wide.scoped_to_self is False


async def test_reaching_across_accounts_is_audited_once() -> None:
    """Once per request, naming what was reached for rather than the rows
    returned: a row per record would grow with the page size and describe the
    same act several times."""
    use_case, audit = _build([_record(who="a2"), _record(who="a2", rid="r2")])

    await use_case.list_page(_actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL), actor_id="a2")

    assert [a for a, _, _ in audit.entries] == [AuditAction.USAGE_READ_ANY]


async def test_reading_your_own_is_not_audited() -> None:
    """The same judgement `prompt_log.list` was given: it is the feature working
    as designed, and a row per screen refresh is noise."""
    use_case, audit = _build([_record()])

    await use_case.list_page(_actor(Scope.USAGE_READ_OWN), actor_id="a1")
    await use_case.list_page(_actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL), actor_id="a1")

    assert audit.entries == []


async def test_the_compacted_filter_keeps_tier_zero() -> None:
    """Tier 0 trims tool definitions and is a compaction like the others. A
    filter written as a truth test would answer "which requests did this
    platform reduce" by hiding the cheapest way it reduces them."""
    use_case, _ = _build(
        [
            _record(tier=0, rid="t0"),
            _record(tier=2, rid="t2"),
            _record(tier=None, rid="none"),
        ]
    )

    compacted = await use_case.list_page(
        _actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL), compacted=True
    )
    untouched = await use_case.list_page(
        _actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL), compacted=False
    )

    assert sorted(e.id for e in compacted.entries) == ["t0", "t2"]
    assert [e.id for e in untouched.entries] == ["none"]


async def test_an_oversized_limit_is_clamped() -> None:
    """The bound every paged read here carries, for the reason they all carry
    it: this table is append-only and anyone holding a key can add rows."""
    use_case, _ = _build([_record()])

    page = await use_case.list_page(
        _actor(Scope.USAGE_READ_OWN, Scope.USAGE_READ_ALL), limit=MAX_LIMIT * 10
    )

    assert page.limit == MAX_LIMIT
