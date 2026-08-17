"""Control plane, tailnet entrance.

Identity comes from the `Tailscale-User-Login` header injected by
`tailscale serve`. This application is published on loopback only.

It is a separate ASGI application from the public entrance rather than a
branch inside one, because the two trust models are incompatible: this one
trusts an identity header outright. If the public entrance shared this
socket, a forged `Tailscale-User-Login` would grant administrator access.
Isolation is by socket binding, not by string comparison.
See docs/architecture/security.md section 5.1.

**CSRF applies here too, which the first version got wrong.** The original
reasoning — "this entrance has no ambient credential" — was false. The
`Tailscale-User-Login` header is ambient in the sense that matters: it is
derived from network position and `tailscale serve` attaches it to *any*
request the browser can be made to issue, including a cross-origin one from a
hostile page open in an administrator's browser. Body-less POSTs are the
reachable set (a JSON body cannot be delivered `no-cors`), which is still
`revoke`, `load`, `unload`, `download` and `invalidate an invitation`. The
double-submit cookie defeats it identically to the public entrance: a
cross-origin page can cause the cookie to be sent but cannot read it to echo
the header.

**No login routes here.** The password and TOTP flow belongs to the entrance
that needs it. Mounting it on both would give an attacker who reached this
socket a second way in that does not depend on the tailnet.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.infrastructure.admin_composition import admin_lifespan, mount_admin_routers
from app.infrastructure.config import get_settings
from app.infrastructure.logging_config import configure_logging
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.body_limit import BodySizeLimitMiddleware
from app.interfaces.http.middleware.csrf import CsrfMiddleware
from app.interfaces.http.middleware.identity import current_actor, resolve_tailnet_actor
from app.interfaces.http.middleware.metrics import MetricsMiddleware
from app.interfaces.http.request_context import RequestContextMiddleware
from app.interfaces.http.schemas.admin_schemas import AdminErrorResponse

TAILSCALE_IDENTITY_HEADERS = ("tailscale-user-login", "tailscale-user-name")


def create_app() -> FastAPI:
    settings = get_settings()
    # Before anything else builds a logger, so no startup line is lost
    # to the WARNING-level fallback handler this replaces.
    configure_logging(settings)

    app = FastAPI(
        title="RCSL AI Nexus Admin (tailnet)",
        docs_url="/docs",
        openapi_url="/openapi.json",
        debug=False,
        # Declares the 422 body the validation handler actually returns.
        # FastAPI's default is its own `HTTPValidationError`, which stopped
        # being true when the admin envelope landed; the generated frontend
        # types were documenting a shape the server does not send.
        responses={422: {"model": AdminErrorResponse}},
        # FastAPI's default is its own `HTTPValidationError`, which stopped
        # being true when the admin envelope landed; the generated frontend
        # types were documenting a shape the server does not send.
        lifespan=admin_lifespan,
    )

    # Innermost, and on this entrance too: the ceiling belongs to the process,
    # not to whichever proxy happens to sit in front of it, and `tailscale
    # serve` sets no body limit at all. See middleware/body_limit.py.
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
    # Outermost user middleware, so every request is counted; see the public
    # entrance for the same note.
    app.add_middleware(MetricsMiddleware)
    # Outermost, so every response — including one built by a rejecting
    # perimeter middleware — carries X-Request-Id. See request_context.py.
    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(
        app, envelope="admin", auth_mode=settings.auth_mode, surface="admin-tailnet"
    )
    mount_admin_routers(app)

    # The one line that decides this application's trust model. Without it
    # `current_actor` raises, so an entrance that forgot to choose fails on
    # its first authenticated request rather than defaulting to anything.
    app.dependency_overrides[current_actor] = resolve_tailnet_actor

    return app


app = create_app()
