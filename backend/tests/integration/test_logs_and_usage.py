"""Audit read and usage bucketing, against a real Postgres.

Two things the unit fakes cannot prove: that the audit read's WHERE clause
isolates tenants the same way every other scoped read does (a tenant must never
see another's trail), and that `date_trunc` groups usage into the buckets the
charts expect. The fake's Python bucketing stands in for the shape; only Postgres
runs the actual SQL.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresAuditLogRepository,
    PostgresTenantRepository,
    PostgresUsageRepository,
)
from app.adapters.persistence.sqlalchemy_models import AuditLogRow
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import UsageRecord

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

NOW = datetime(2026, 7, 25, 12, 30, tzinfo=UTC)


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def _tenant(session, name: str) -> str:
    tid = str(uuid.uuid4())
    await PostgresTenantRepository(session).save(Tenant(id=tid, name=name))
    return tid


async def _audit(session, tenant_id: str, action: str, *, outcome: str = "success") -> None:
    session.add(
        AuditLogRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id="x",
            actor_display="x@example.org",
            actor_source="local",
            action=action,
            target=None,
            outcome=outcome,
            detail={},
            at=NOW,
        )
    )
    await session.flush()


async def test_audit_read_is_scoped_to_the_tenant(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")
    await _audit(session, a, "user.invited")
    await _audit(session, b, "key.revoked")

    entries = await PostgresAuditLogRepository(session, a).list_entries(
        action=None, outcome=None, actor_id=None, since=None, until=None, limit=50, offset=0
    )
    assert [e.action for e in entries] == ["user.invited"]

    count = await PostgresAuditLogRepository(session, a).count_entries(
        action=None, outcome=None, actor_id=None, since=None, until=None
    )
    assert count == 1, "the count matches the tenant-scoped page, not the whole table"


async def test_audit_read_filters_and_orders_newest_first(session) -> None:
    a = await _tenant(session, "A")
    session.add_all(
        [
            AuditLogRow(
                id=str(uuid.uuid4()),
                tenant_id=a,
                actor_id="x",
                actor_display="x@example.org",
                actor_source="local",
                action="model.loaded" if i % 2 else "user.invited",
                target=None,
                outcome="success" if i % 2 else "failure",
                detail={},
                at=NOW + timedelta(minutes=i),
            )
            for i in range(4)
        ]
    )
    await session.flush()

    repo = PostgresAuditLogRepository(session, a)
    only_failures = await repo.list_entries(
        action=None, outcome="failure", actor_id=None, since=None, until=None, limit=50, offset=0
    )
    assert {e.outcome for e in only_failures} == {"failure"}

    everything = await repo.list_entries(
        action=None, outcome=None, actor_id=None, since=None, until=None, limit=50, offset=0
    )
    ats = [e.at for e in everything]
    assert ats == sorted(ats, reverse=True), "newest first"


async def test_usage_buckets_by_hour_and_capability(session) -> None:
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")

    def rec(tenant: str, cap: str, at: datetime, tokens: int) -> UsageRecord:
        return UsageRecord(
            id=str(uuid.uuid4()),
            actor_id="x",
            api_key_id="k",
            capability=cap,
            model_alias="m",
            tokens=tokens,
            latency_ms=1,
            completed=True,
            at=at,
            tenant_id=tenant,
        )

    repo_a = PostgresUsageRepository(session, a)
    await repo_a.record(rec(a, "chat", NOW.replace(hour=10, minute=30), 7))
    await repo_a.record(rec(a, "chat", NOW.replace(hour=11, minute=15), 10))
    await repo_a.record(rec(a, "chat", NOW.replace(hour=11, minute=45), 5))
    await repo_a.record(rec(a, "embed", NOW.replace(hour=11, minute=20), 3))
    # Another tenant's row in the same window must not appear.
    await PostgresUsageRepository(session, b).record(rec(b, "chat", NOW.replace(hour=11), 99))
    await session.flush()

    since = NOW - timedelta(hours=24)
    until = NOW + timedelta(hours=1)
    buckets = await repo_a.bucketed_usage(since, until, "hour")

    got = {(b.bucket_start.hour, b.capability): (b.requests, b.tokens) for b in buckets}
    assert got == {
        (10, "chat"): (1, 7),
        (11, "chat"): (2, 15),
        (11, "embed"): (1, 3),
    }


async def test_own_usage_narrows_by_actor_and_still_by_tenant(session) -> None:
    """The `actor_id` filter, which only SQL can be wrong about.

    The unit tests fold a Python stand-in for `date_trunc`, so the thing they
    cannot prove is that the predicate reaches the query and lands *inside* the
    tenant scope rather than replacing it. Both halves are asserted here: the
    other account's row in the same tenant is excluded, and the same actor id
    in another tenant is excluded too.
    """
    a = await _tenant(session, "A")
    b = await _tenant(session, "B")

    def rec(tenant: str, actor: str, at: datetime, tokens: int) -> UsageRecord:
        return UsageRecord(
            id=str(uuid.uuid4()),
            actor_id=actor,
            api_key_id="k",
            capability="chat",
            model_alias="m",
            tokens=tokens,
            latency_ms=1,
            completed=True,
            at=at,
            tenant_id=tenant,
        )

    repo_a = PostgresUsageRepository(session, a)
    await repo_a.record(rec(a, "mine", NOW.replace(hour=10, minute=30), 7))
    await repo_a.record(rec(a, "mine", NOW.replace(hour=11, minute=15), 5))
    await repo_a.record(rec(a, "theirs", NOW.replace(hour=11, minute=20), 100))
    # The same person's id under another tenant. Reachable only if the actor
    # filter were applied instead of the tenant one rather than alongside it.
    await PostgresUsageRepository(session, b).record(
        rec(b, "mine", NOW.replace(hour=11, minute=30), 1000)
    )
    await session.flush()

    since = NOW - timedelta(hours=24)
    until = NOW + timedelta(hours=1)
    buckets = await repo_a.bucketed_usage(since, until, "hour", actor_id="mine")

    got = {b.bucket_start.hour: (b.requests, b.tokens) for b in buckets}
    assert got == {10: (1, 7), 11: (1, 5)}
