"""Session lifetime and invalidation.

The invalidation cases are the ones worth pinning. "Changing a password ends
every other session" is implemented with a watermark rather than an index
(see the module docstring), and a watermark that is written but never
consulted looks exactly like one that works.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.session.session_store import SessionStore

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def build(absolute: int = 3600, idle: int = 600) -> SessionStore:
    return SessionStore(InMemoryCache(), absolute_ttl=absolute, idle_ttl=idle)


async def test_a_new_session_reads_back() -> None:
    store = build()
    created = await store.create("u1", NOW)

    read = await store.read(created.session_id, NOW)

    assert read is not None
    assert read.user_id == "u1"
    assert read.csrf_token == created.csrf_token


async def test_each_session_gets_a_distinct_identifier() -> None:
    """Fixation defence. Identifiers are minted here and never adopted from
    anything the client presented, so two logins cannot share one."""
    store = build()
    first = await store.create("u1", NOW)
    second = await store.create("u1", NOW)

    assert first.session_id != second.session_id
    assert first.csrf_token != second.csrf_token


async def test_absolute_expiry_ends_a_session_even_while_it_is_in_use() -> None:
    """The idle window is refreshed on every read, so without a separate
    absolute limit an active session would never expire at all."""
    store = build(absolute=3600, idle=600)
    created = await store.create("u1", NOW)

    assert await store.read(created.session_id, NOW + timedelta(minutes=5)) is not None
    assert await store.read(created.session_id, NOW + timedelta(hours=2)) is None


async def test_changing_a_password_ends_other_sessions_and_keeps_the_callers() -> None:
    store = build()
    mine = await store.create("u1", NOW)
    theirs = await store.create("u1", NOW)

    later = NOW + timedelta(seconds=1)
    await store.invalidate_others("u1", mine.session_id, later)

    assert await store.read(theirs.session_id, later) is None
    assert await store.read(mine.session_id, later) is not None


async def test_the_kept_session_does_not_gain_a_longer_life() -> None:
    """Re-stamping is how the caller's session survives the watermark. If it
    also moved the absolute expiry, changing a password every few hours would
    keep one session alive indefinitely."""
    store = build(absolute=3600, idle=600)
    mine = await store.create("u1", NOW)

    later = NOW + timedelta(minutes=30)
    await store.invalidate_others("u1", mine.session_id, later)

    read = await store.read(mine.session_id, later)
    assert read is not None
    assert read.expires_at == mine.expires_at


async def test_a_consumed_reset_ends_every_session() -> None:
    store = build()
    first = await store.create("u1", NOW)
    second = await store.create("u1", NOW)

    later = NOW + timedelta(seconds=1)
    await store.invalidate_all("u1", later)

    assert await store.read(first.session_id, later) is None
    assert await store.read(second.session_id, later) is None


async def test_invalidation_does_not_reach_another_user() -> None:
    store = build()
    mine = await store.create("u1", NOW)
    other = await store.create("u2", NOW)

    later = NOW + timedelta(seconds=1)
    await store.invalidate_all("u1", later)

    assert await store.read(mine.session_id, later) is None
    assert await store.read(other.session_id, later) is not None


async def test_a_destroyed_session_is_gone_immediately() -> None:
    store = build()
    created = await store.create("u1", NOW)

    await store.destroy(created.session_id)

    assert await store.read(created.session_id, NOW) is None
