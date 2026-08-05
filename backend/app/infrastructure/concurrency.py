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

from app.domain.exceptions import ServerOverloadedError


class SemaphoreConcurrencyLimiter:
    def __init__(self, limit: int, queue_wait_seconds: int = 0) -> None:
        """`queue_wait_seconds` bounds how long a request may sit waiting for a
        slot; zero or negative waits forever, which was the only behaviour
        before 2026-08-05.

        Unbounded waiting is not neutral. A slot can legitimately be held for
        up to 25 minutes (read timeout plus generation deadline), so a caller
        arriving with every slot busy sat in an invisible queue producing zero
        bytes — no status, no code — until their own client timeout killed the
        connection, which reads exactly like a hung deployment. A bounded wait
        turns that silence into `503 overloaded` with a `Retry-After`, the code
        that makes "busy" distinguishable from "broken".
        """
        if limit < 1:
            raise ValueError("concurrency limit must be at least 1")
        self._semaphore = asyncio.Semaphore(limit)
        self._limit = limit
        self._queue_wait_seconds = queue_wait_seconds

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self._queue_wait_seconds > 0:
            try:
                async with asyncio.timeout(self._queue_wait_seconds):
                    await self._semaphore.acquire()
            except TimeoutError:
                raise ServerOverloadedError(
                    detail=f"no slot freed within {self._queue_wait_seconds}s; "
                    f"all {self._limit} inference slots held for the whole wait"
                ) from None
        else:
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
