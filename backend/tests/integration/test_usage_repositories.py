from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.persistence.repositories import (
    PostgresUsageRepository,
)
from app.domain.entities.usage import UsageRecord
from tests.integration.repository_fixtures import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.repository_fixtures",)


async def test_usage_totals_only_count_the_named_key(session) -> None:
    repo = PostgresUsageRepository.unscoped(session)
    now = datetime.now(UTC)
    for key_id, tokens in (("k1", 100), ("k1", 50), ("k2", 999)):
        await repo.record(
            UsageRecord(
                id=str(uuid.uuid4()),
                actor_id="u1",
                api_key_id=key_id,
                capability="chat",
                model_alias="primary",
                tokens=tokens,
                latency_ms=10,
                completed=True,
                at=now,
            )
        )
    await session.flush()

    assert await repo.tokens_used_today("k1") == 150


async def test_a_spent_quota_recovers_one_past_request_at_a_time(session) -> None:
    """The window trails 24 hours rather than resetting at midnight, so the
    wait after exhausting a quota is set by when the *oldest* spend ages out —
    and only by as much of it as has to go. Three requests of 100 against a
    quota of 250 sit 50 over; releasing the first 100 is enough, so the wait
    runs from that one, not from the newest and not from all three.

    Getting this wrong is invisible in the response: it is still a 429, just
    with a `Retry-After` that sends the caller back too early or too late.
    """
    repo = PostgresUsageRepository.unscoped(session)
    now = datetime.now(UTC)
    ages = (timedelta(hours=20), timedelta(hours=10), timedelta(minutes=5))
    for age in ages:
        await repo.record(
            UsageRecord(
                id=str(uuid.uuid4()),
                actor_id="u1",
                api_key_id="k3",
                capability="chat",
                model_alias="primary",
                tokens=60,
                prompt_tokens=40,
                latency_ms=10,
                completed=True,
                at=now - age,
            )
        )
    await session.flush()

    assert await repo.tokens_used_today("k3") == 300

    # 300 used against a quota of 250: release 51 to be admitted again.
    recovers_at = await repo.quota_recovers_at("k3", tokens_to_release=300 - 250 + 1)
    assert recovers_at is not None
    expected = now - timedelta(hours=20) + timedelta(days=1)
    assert abs((recovers_at - expected).total_seconds()) < 1

    # Needing more than the window holds cannot be answered from it.
    assert await repo.quota_recovers_at("k3", tokens_to_release=301) is None
