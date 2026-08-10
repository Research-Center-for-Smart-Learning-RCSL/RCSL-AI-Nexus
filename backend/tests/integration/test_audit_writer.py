"""The audit *writer*, against a real Postgres.

Every other test of the audit trail uses `FakeAudit`, which accepts anything.
That is the gap this file exists for: `PostgresAudit.record` deliberately
swallows its own failures — losing the event beats turning a successful
administrative action into a 500 — so a row the database refuses disappears
with nothing but an application-log line to show for it. A fake can never
notice that, and the events added on 2026-08-02 are precisely the ones whose
values arrive from an unauthenticated caller.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.persistence.sqlalchemy_models import AuditLogRow
from app.application.audit_subject import unknown_subject
from app.domain.entities.actor import Actor, Role
from app.domain.entities.audit import AuditAction
from app.shared.clock import FixedClock

from .test_logs_and_usage import NOW

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
async def writer_and_session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    audit = PostgresAudit(factory, FixedClock(NOW))
    async with factory() as s:
        yield audit, s
    await engine.dispose()


async def _rows(session) -> list[AuditLogRow]:
    return list((await session.execute(select(AuditLogRow))).scalars())


async def test_a_failed_login_for_an_unknown_account_actually_lands(writer_and_session) -> None:
    """`unknown_subject` puts a non-uuid in `actor_id`, which is a
    fixed-width column. If the schema ever gained a constraint or a foreign key
    there, every failed-login record would vanish into the swallowed-exception
    path and the audit log would look quiet rather than broken.
    """
    audit, session = writer_and_session

    await audit.record(
        unknown_subject("nobody@example.org"),
        AuditAction.USER_SIGN_IN_FAILED,
        target="unknown",
        outcome="failed",
        detail={"client_ip": "203.0.113.7", "reason": "unknown_login"},
    )

    (row,) = await _rows(session)
    assert (row.action, row.outcome) == ("user.sign_in_failed", "failed")
    assert row.actor_display == "nobody@example.org"
    assert row.detail["reason"] == "unknown_login"


async def test_an_over_long_target_is_trimmed_rather_than_dropped(writer_and_session) -> None:
    """`target` on an authorization failure is the request path, and nothing
    bounds a path. Postgres refuses an over-long value instead of trimming it,
    so without `_fit` a few hundred characters of padding in a URL would
    suppress the record of someone probing — a way to be refused without
    leaving a trace.
    """
    audit, session = writer_and_session
    actor = Actor(
        id="u1", display="someone@example.org", role=Role.USER, source="local", scopes=frozenset()
    )

    await audit.record(
        actor, AuditAction.AUTHZ_DENIED, target="/admin/models/" + "A" * 5000, outcome="denied"
    )

    (row,) = await _rows(session)
    assert len(row.target) == 255
    assert row.target.startswith("/admin/models/AAA")
    # The marker is what stops a trimmed value being read as the whole one.
    assert row.target.endswith("…")


async def test_a_maximum_length_login_is_not_trimmed(writer_and_session) -> None:
    """`LoginRequest.login` is bounded at 255 and `actor_display` is 255 wide.
    They match exactly, so the longest login a caller can send must still be
    recorded verbatim; a narrower column would trim every one of them.
    """
    audit, session = writer_and_session
    login = "a" * 243 + "@example.org"
    assert len(login) == 255

    await audit.record(unknown_subject(login), AuditAction.USER_SIGN_IN_FAILED, outcome="failed")

    (row,) = await _rows(session)
    assert row.actor_display == login
