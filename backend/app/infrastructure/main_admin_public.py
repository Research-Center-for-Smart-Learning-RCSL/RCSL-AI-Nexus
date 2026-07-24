"""Control plane, public entrance.

Reached through the external openresty proxy. Identity comes from a
server-side session established by password plus TOTP.

The header-stripping middleware below is the single most important line of
defence in this process: the tailnet application trusts
`Tailscale-User-Login` outright, so anything arriving here carrying that
header must have it removed before any handler can observe it. nginx clears
the same headers as an outer layer, and this is the inner one.
See docs/architecture/security.md section 5.1.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.infrastructure.config import get_settings
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.routers import health

STRIPPED_HEADER_PREFIX = b"tailscale-"


class StripTailscaleHeadersMiddleware(BaseHTTPMiddleware):
    """Remove every `Tailscale-*` header, unconditionally.

    Not "validate", not "ignore if suspicious": remove. There is no
    legitimate way for one of these to arrive on this entrance, and the cost
    of being wrong is a full administrator bypass.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.scope["headers"] = [
            (name, value)
            for name, value in request.scope["headers"]
            if not name.lower().startswith(STRIPPED_HEADER_PREFIX)
        ]
        return await call_next(request)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RCSL AI Nexus Admin (public)",
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        debug=False,
    )

    app.add_middleware(StripTailscaleHeadersMiddleware)

    install_error_handlers(app, envelope="admin")
    app.include_router(health.router)

    return app


app = create_app()
