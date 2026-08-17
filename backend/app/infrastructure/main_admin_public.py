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

from functools import partial

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
from app.interfaces.http.middleware.body_limit import BodySizeLimitMiddleware
from app.interfaces.http.middleware.csrf import CsrfMiddleware
from app.interfaces.http.middleware.geo_middleware import GeoFilterMiddleware
from app.interfaces.http.middleware.identity import (
    current_actor,
    current_session,
    resolve_session_actor,
    session_from_request,
)
from app.interfaces.http.middleware.metrics import MetricsMiddleware
from app.interfaces.http.request_context import RequestContextMiddleware
from app.interfaces.http.routers import auth
from app.interfaces.http.schemas.admin_schemas import AdminErrorResponse

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
        # Declares the 422 body the validation handler actually returns.
        # FastAPI's default is its own `HTTPValidationError`, which stopped
        # being true when the admin envelope landed; the generated frontend
        # types were documenting a shape the server does not send.
        responses={422: {"model": AdminErrorResponse}},
        # FastAPI's default is its own `HTTPValidationError`, which stopped
        # being true when the admin envelope landed; the generated frontend
        # types were documenting a shape the server does not send.
        # No node heartbeat here. The lifespan is shared with the tailnet
        # entrance, which owns the sweep; running it in both had the two
        # processes writing the same rows every thirty seconds.
        lifespan=partial(admin_lifespan, run_node_heartbeat=False),
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
    #   Csrf — needs the request to have survived the perimeter.
    #   BodySizeLimit (innermost) — the last thing before the router, because
    #     it is the only one of these the *router* can defeat by reading the
    #     body first. Authentication here is a route dependency and FastAPI
    #     parses the body ahead of dependencies, so without this an anonymous
    #     caller reached an allocation bounded only by nginx. See
    #     middleware/body_limit.py.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.admin_max_body_bytes,
        envelope="admin",
    )
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
    # Outermost, so every response — including one built by a rejecting
    # perimeter middleware — carries X-Request-Id. See request_context.py.
    app.add_middleware(RequestContextMiddleware)

    # `/readyz` answers only {"ready": bool} here, without naming the failing
    # dependency, because this entrance faces the internet and the endpoint is
    # exempt from the perimeter checks so a prober can reach it.
    app.state.expose_readiness_detail = False

    # `local`, not `settings.auth_mode`: the value names *this entrance's*
    # authentication, and the frontend decides from it whether a 401 means
    # "reconnect to the tailnet" or "go to the login screen". `auth_mode` is
    # deployment-wide and reads `tailnet` here, so the public entrance was
    # telling a browser on the internet that its Tailscale connection had
    # dropped, and `app-shell.tsx` then skipped the redirect to /login — the
    # front door of the entrance, unreachable, on a control whose whole
    # purpose is to tell the two entrances apart. This entrance is always
    # session-based whatever the deployment mode: it is the only one that
    # mounts the credential flow, below.
    install_error_handlers(app, envelope="admin", auth_mode="local", surface="admin-public")
    mount_admin_routers(app)
    # Only this entrance mounts the credential flow. See the tailnet module.
    app.include_router(auth.router, prefix=ADMIN_PREFIX)

    app.dependency_overrides[current_actor] = resolve_session_actor
    app.dependency_overrides[current_session] = session_from_request

    return app


app = create_app()
