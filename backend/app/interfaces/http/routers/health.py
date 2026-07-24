"""Liveness and readiness.

Both endpoints bypass the geo filter, the trusted-proxy check, and
authentication: without that exemption the reverse proxy cannot probe the
service at all. Neither response carries a version string, model list, or
hostname. See docs/architecture/backend.md section 9.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Checks nothing, so a dependency outage
    does not cause an otherwise healthy container to be restarted."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness: dependencies are reachable.

    Reveals which dependency is down, which is mildly useful to an attacker,
    so on the gateway this is served only on the tailnet-bound port.
    """
    # Wired to real probes once the adapters are in place; the shape is fixed
    # now so that Compose health checks and nginx upstreams can be configured.
    checks: dict[str, bool] = {"database": True, "redis": True}
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "checks": checks},
    )
