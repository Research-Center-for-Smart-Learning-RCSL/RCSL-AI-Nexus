"""Job progress, held on `CachePort`.

Outside the process that produces it, deliberately. A download runs as a
detached task; if the container restarts mid-pull, the task is gone and
nothing will ever finish it. Keeping progress in the cache means the job is
then visibly stale rather than silently absent, and the UI can say so instead
of spinning forever.

The entries expire. A finished job is a fact about the past, and the registry
already records the outcome in the model's state, so there is nothing here
worth a table.
"""

from __future__ import annotations

import json

from app.domain.ports.infrastructure_ports import CachePort, JobStatus

KEY_PREFIX = "job:"


class CacheJobProgress:
    def __init__(self, cache: CachePort) -> None:
        self._cache = cache

    async def set(self, status: JobStatus, ttl_seconds: int) -> None:
        await self._cache.set(_key(status.job_id), _encode(status), ttl_seconds=ttl_seconds)

    async def get(self, job_id: str) -> JobStatus | None:
        raw = await self._cache.get(_key(job_id))
        if raw is None:
            return None
        return _decode(job_id, raw)


def _key(job_id: str) -> str:
    return f"{KEY_PREFIX}{job_id}"


def _encode(status: JobStatus) -> str:
    return json.dumps(
        {
            "state": status.state,
            "target": status.target,
            "progress": status.progress,
            "completed_bytes": status.completed_bytes,
            "total_bytes": status.total_bytes,
            "message": status.message,
        }
    )


def _decode(job_id: str, raw: str) -> JobStatus | None:
    try:
        payload = json.loads(raw)
        return JobStatus(
            job_id=job_id,
            state=str(payload["state"]),
            target=payload.get("target"),
            progress=payload.get("progress"),
            completed_bytes=payload.get("completed_bytes"),
            total_bytes=payload.get("total_bytes"),
            message=payload.get("message"),
        )
    except (ValueError, TypeError, KeyError):
        # Treated as absent rather than raised. A format change should log the
        # user out of a progress bar, not return 500 on every poll.
        return None
