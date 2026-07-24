"""Cache adapters.

Two implementations of `CachePort`. Redis is the real one; the in-memory
version exists so the stack runs on a developer machine that is not running
Compose, and so tests do not need a container.

The in-memory one is **per process**, which makes it wrong for anything that
counts across requests handled by different workers. That is acceptable only
because it is never selected outside development; `CACHE_BACKEND` chooses, and
it is not inferred from anything else.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis


class RedisCache:
    def __init__(self, url: str, password: str | None = None) -> None:
        self._redis: Redis = Redis.from_url(url, password=password or None, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        """Increment and return the new value, setting a TTL on first use.

        The TTL is applied in the same pipeline as the increment, so a crash
        between the two cannot leave a counter that never expires and blocks a
        key forever.
        """
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl_seconds, nx=True)
            result = await pipe.execute()
        return int(result[0])

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryCache:
    """Development and test only. Not shared between processes."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}

    def _live(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= time.monotonic():
            del self._values[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._values[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        current = int(self._live(key) or 0) + 1
        expires_at = self._values.get(key, (None, time.monotonic() + ttl_seconds))[1]
        self._values[key] = (str(current), expires_at)
        return current

    async def close(self) -> None:
        self._values.clear()
