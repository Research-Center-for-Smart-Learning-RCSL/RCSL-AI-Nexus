"""Global inference concurrency limit.

Implements `ConcurrencyLimiterPort`. `slot()` is an async context manager so
callers hold it via `async with` around the whole generator body, which is
what guarantees release on client disconnect as well as on normal
completion. See docs/architecture/backend.md section 6.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class SemaphoreConcurrencyLimiter:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("concurrency limit must be at least 1")
        self._semaphore = asyncio.Semaphore(limit)
        self._limit = limit

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()

    @property
    def available(self) -> int:
        return self._semaphore._value  # noqa: SLF001  (test and metrics only)

    @property
    def limit(self) -> int:
        return self._limit
