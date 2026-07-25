"""Liveness and readiness.

Both bypass the geo filter, the trusted-proxy check, and authentication:
without that exemption the reverse proxy cannot probe the service at all.
Neither response carries a version string, model list, or hostname.
See docs/architecture/backend.md section 9.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.infrastructure.db import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

PROBE_TIMEOUT_SECONDS = 3.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up.

    Checks nothing on purpose. A dependency outage must not cause an otherwise
    healthy container to be restarted, which would turn a database blip into a
    restart loop.
    """
    return {"status": "ok"}


async def _check_database() -> bool:
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return True


async def _probe(name: str, coro: Awaitable[bool]) -> tuple[str, bool]:
    """Run one dependency check, bounded and never raising.

    A readiness probe that hangs is worse than one that reports failure: the
    orchestrator waits instead of acting.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await coro
        return name, True
    except Exception:  # noqa: BLE001
        logger.warning("readiness probe failed: %s", name, exc_info=True)
        return name, False


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: dependencies are actually reachable.

    This previously returned hardcoded booleans and could never report 503, so
    anything gating a rollout on it was gating on a constant.

    The per-dependency breakdown is returned only when the caller was not
    resolved through the public perimeter. Which dependency is down is mildly
    useful to an attacker, and on the public admin entrance this endpoint is
    exempt from the geo and proxy checks so a health prober can reach it — so
    there it answers only `{"ready": bool}`.
    """
    probes = [_probe("database", _check_database())]

    cache = getattr(request.app.state, "cache", None)
    if cache is not None:
        probes.append(_probe("cache", cache.get("readyz")))

    runtimes = getattr(request.app.state, "runtimes", None)
    if runtimes:
        runtime = next(iter(runtimes.values()))
        probes.append(_probe("runtime", runtime.health()))

    checks = dict(await asyncio.gather(*probes))
    ready = all(checks.values())

    body: dict[str, object] = {"ready": ready}
    # Detail only where the perimeter is not the public one. The public admin
    # and gateway entrances strip it; the tailnet entrance and local
    # development keep it, which is where an operator actually reads it.
    if getattr(request.app.state, "expose_readiness_detail", True):
        body["checks"] = checks

    return JSONResponse(status_code=200 if ready else 503, content=body)
