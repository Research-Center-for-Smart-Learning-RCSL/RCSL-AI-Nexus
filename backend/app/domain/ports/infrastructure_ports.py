"""Ports for caching, background job progress, and metrics."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


class CachePort(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, ttl_seconds: int) -> int:
        """Increment and return the new value, setting a TTL on first use.
        Backs rate limiting for both API keys and login attempts."""
        ...


@dataclass(frozen=True, slots=True)
class JobStatus:
    job_id: str
    state: str
    """queued | running | succeeded | failed"""

    target: str | None = None
    """What the job is acting on. The model id, for a download."""

    progress: float | None = None
    """0 to 1, or None while the runtime has not reported a total. Ollama
    sends manifest and verification stages with no byte counts at all, so a
    progress bar that assumed a number here would sit at zero and then jump."""

    completed_bytes: int | None = None
    total_bytes: int | None = None
    message: str | None = None


class JobProgressPort(Protocol):
    """Progress for long-running work such as a model download.

    Progress lives outside the process that produces it, so a restart during
    a pull leaves a visibly stale job rather than one that silently vanished.
    """

    async def set(self, status: JobStatus, ttl_seconds: int) -> None: ...
    async def get(self, job_id: str) -> JobStatus | None: ...


class MetricsPort(Protocol):
    """Phase 2. Until then the memory budget uses static node capacity."""

    async def free_memory_gb(self, node_id: str) -> float | None: ...


class ConcurrencyLimiterPort(Protocol):
    """Caps simultaneous inference.

    With no CDN in front of this deployment, every request reaches the
    hardware. On unified memory an unbounded number of concurrent
    generations does not degrade gracefully, it swaps. `slot()` is an async
    context manager so the limit is held for the whole generator lifetime
    rather than just the call that starts it.
    """

    def slot(self) -> AbstractAsyncContextManager[None]: ...

    @property
    def available(self) -> int:
        """Slots free right now. Read by the saturation gauge, which is the one
        pressure the resource guardrails exist to bound."""
        ...

    @property
    def limit(self) -> int:
        """Total slots configured."""
        ...
