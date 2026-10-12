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
