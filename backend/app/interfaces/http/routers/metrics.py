"""Prometheus scrape endpoint, on all three applications.

Guarded by a bearer token from a file secret, not by network placement alone.
Placement is the outer control (Prometheus scrapes over a dedicated internal
network and publishes no port of its own), but the gateway carries this endpoint
on the same ASGI app that faces the proxy, so a second, independent control that
does not depend on the operator's nginx being precise is warranted. The token is
the same shared-secret pattern the trusted-proxy check already uses.

A missing or wrong token returns 404, not 401: an unauthenticated caller learns
nothing, not even that the endpoint exists, matching how the perimeter declines
to name the control that rejected it. The exposition body carries request rates,
model names and latencies, so leaking it is a real information disclosure, which
is why the label set never includes a caller identity (see the metrics adapter).
"""

from __future__ import annotations

from hmac import compare_digest

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.adapters.metrics.prometheus import Metrics, render
from app.infrastructure.config import get_settings

router = APIRouter(tags=["metrics"])

_BEARER_PREFIX = "Bearer "


def _authorized(request: Request, token: str) -> bool:
    if not token:
        return False
    header = request.headers.get("authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return False
    presented = header[len(_BEARER_PREFIX) :]
    return compare_digest(presented.encode("utf-8"), token.encode("utf-8"))


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    settings = get_settings()
    if not settings.metrics_enabled or not _authorized(request, settings.metrics_scrape_token):
        return Response(status_code=404)

    instruments: Metrics | None = getattr(request.app.state, "metrics", None)
    if instruments is None:
        return Response(status_code=404)

    body, content_type = render(instruments)
    return Response(content=body, media_type=content_type)
