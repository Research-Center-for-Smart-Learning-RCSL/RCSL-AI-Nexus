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

from app.infrastructure.admin_composition import (
    ADMIN_PREFIX,
    admin_lifespan,
    mount_admin_routers,
)
from app.infrastructure.config import get_settings
from app.infrastructure.logging_config import configure_logging
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.csrf import CsrfMiddleware
from app.interfaces.http.middleware.geo_middleware import GeoFilterMiddleware
from app.interfaces.http.middleware.identity import (
    current_actor,
    current_session,
    resolve_session_actor,
    session_from_request,
)
from app.interfaces.http.middleware.metrics import MetricsMiddleware
from app.interfaces.http.routers import auth

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
    # Before anything else builds a logger, so no startup line is lost
    # to the WARNING-level fallback handler this replaces.
    configure_logging(settings)

    app = FastAPI(
        title="RCSL AI Nexus Admin (public)",
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        debug=False,
        lifespan=admin_lifespan,
    )

    # Starlette runs middleware in reverse order of registration, so the last
    # registered runs outermost. The order that matters:
    #
    #   MetricsMiddleware (outermost) — only observes; it reads no request
    #     content and makes no trust decision, so counting a request before the
    #     perimeter runs is deliberate and safe.
    #   StripTailscaleHeaders — a forged identity header must be gone before any
    #     handler or trust-bearing middleware in this process can look at it.
    #   GeoFilter — rejects a caller outside the allowed countries, and (via
    #     resolve_client_ip) one that did not arrive through the proxy, before
    #     a handler or the CSRF cookie logic runs.
    #   Csrf (innermost) — needs the request to have survived the perimeter.
    app.add_middleware(
        CsrfMiddleware,
        cookie_name=settings.effective_csrf_cookie,
        header_name=settings.csrf_header_name,
        secure=settings.cookie_secure,
        max_age_seconds=settings.session_absolute_ttl_seconds,
    )
    app.add_middleware(GeoFilterMiddleware, auth_mode=settings.auth_mode)
    app.add_middleware(StripTailscaleHeadersMiddleware)
    # Outermost, so a request rejected at the perimeter is still counted rather
    # than invisible. /metrics itself is exempt from the geo check below and
    # rests on its bearer token; see routers/metrics.py.
    app.add_middleware(MetricsMiddleware)

    # `/readyz` answers only {"ready": bool} here, without naming the failing
    # dependency, because this entrance faces the internet and the endpoint is
    # exempt from the perimeter checks so a prober can reach it.
    app.state.expose_readiness_detail = False

    install_error_handlers(app, envelope="admin", auth_mode=settings.auth_mode)
    mount_admin_routers(app)
    # Only this entrance mounts the credential flow. See the tailnet module.
    app.include_router(auth.router, prefix=ADMIN_PREFIX)

    app.dependency_overrides[current_actor] = resolve_session_actor
    app.dependency_overrides[current_session] = session_from_request

    return app


app = create_app()
