"""The production Redis SET NX winner and bounded first-record lookup."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.adapters.cache.redis_adapter import RedisCache

REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set")


async def test_independent_workers_replay_one_atomic_winner():
    clients = [RedisCache(REDIS_URL or "") for _ in range(8)]
    key = f"grounding-test:{uuid.uuid4()}"
    try:
        won = await asyncio.gather(
            *[
                client.set_if_absent(key, f"rendered-context-{index}", 60)
                for index, client in enumerate(clients)
            ]
        )
        assert sum(won) == 1
        winner = f"rendered-context-{won.index(True)}"
        assert await asyncio.gather(*[client.get(key) for client in clients]) == [winner] * 8
    finally:
        await clients[0].delete(key)
        await asyncio.gather(*[client.close() for client in clients])


async def test_first_lookup_returns_only_the_newest_available_record():
    client = RedisCache(REDIS_URL or "")
    prefix = f"grounding-test:{uuid.uuid4()}"
    keys = [f"{prefix}:{index}" for index in range(256)]
    try:
        assert await client.get_first(keys) is None
        await client.set(keys[255], "older-chain", 60)
        await client.set(keys[1], "newer-chain", 60)
        assert await client.get_first(keys) == (keys[1], "newer-chain")
    finally:
        for key in (keys[1], keys[255]):
            await client.delete(key)
        await client.close()


async def test_atomic_quotas_bound_concurrent_tenants_and_reject_oversized_records(monkeypatch):
    from app.domain.services.grounding_records import MAX_GROUNDING_RECORD_BYTES

    monkeypatch.setattr("app.adapters.cache.redis_adapter.MAX_GROUNDING_RECORDS_PER_TENANT", 2)
    monkeypatch.setattr("app.adapters.cache.redis_adapter.MAX_GROUNDING_RECORDS_TOTAL", 3)
    client = RedisCache(REDIS_URL or "")
    prefix = f"grounding-test:{uuid.uuid4()}"
    monkeypatch.setattr(
        "app.adapters.cache.redis_adapter.GROUNDING_QUOTA_PREFIX", prefix + ":quota"
    )
    try:
        assert not await client.set_grounding_if_absent(
            "a", prefix, "x" * (MAX_GROUNDING_RECORD_BYTES + 1), 30
        )
        won = await asyncio.gather(
            *[client.set_grounding_if_absent("a", f"{prefix}:{i}", "record", 30) for i in range(8)]
        )
        assert sum(won) == 2
        assert await client.set_grounding_if_absent("b", f"{prefix}:b", "record", 30)
        assert not await client.set_grounding_if_absent("c", f"{prefix}:c", "record", 30)
        assert await client._redis.zcard(prefix + ":quota:global") == 3
    finally:
        keys = [key async for key in client._redis.scan_iter(match=prefix + "*")]
        if keys:
            await client._redis.delete(*keys)
        await client.close()


async def test_expired_quota_reopens_without_shortening_other_records(monkeypatch):
    monkeypatch.setattr("app.adapters.cache.redis_adapter.MAX_GROUNDING_RECORDS_TOTAL", 2)
    client = RedisCache(REDIS_URL or "")
    prefix = f"grounding-test:{uuid.uuid4()}"
    monkeypatch.setattr(
        "app.adapters.cache.redis_adapter.GROUNDING_QUOTA_PREFIX", prefix + ":quota"
    )
    try:
        assert await client.set_grounding_if_absent("long", prefix + ":long", "record", 60)
        assert await client.set_grounding_if_absent("short", prefix + ":short", "record", 1)
        assert await client._redis.ttl(prefix + ":quota:global") > 50
        await asyncio.sleep(1.05)
        assert await client.set_grounding_if_absent("new", prefix + ":new", "record", 30)
        assert await client.get(prefix + ":long") == "record"
        assert not await client.set_grounding_if_absent("new2", prefix + ":new2", "record", 30)
    finally:
        keys = [key async for key in client._redis.scan_iter(match=prefix + "*")]
        if keys:
            await client._redis.delete(*keys)
        await client.close()
