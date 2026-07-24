"""Control plane, tailnet entrance.

Identity comes from the `Tailscale-User-Login` header injected by
`tailscale serve`. This application is published on loopback only.

It is a separate ASGI application from the public entrance rather than a
branch inside one, because the two trust models are incompatible: this one
trusts an identity header outright. If the public entrance shared this
socket, a forged `Tailscale-User-Login` would grant administrator access.
Isolation is by socket binding, not by string comparison.
See docs/architecture/security.md section 5.1.

**No CSRF middleware here, and that is not an omission.** CSRF protects an
ambient credential: a cookie the browser attaches to any request a hostile
page can provoke. This entrance has none. Identity arrives in a header that
`tailscale serve` adds, and no cross-origin page can cause that to happen.

**No login routes here either.** The password and TOTP flow belongs to the
entrance that needs it. Mounting it on both would give an attacker who
reached this socket a second way in that does not depend on the tailnet.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.infrastructure.admin_composition import admin_lifespan, mount_admin_routers
from app.infrastructure.config import get_settings
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.identity import current_actor, resolve_tailnet_actor

TAILSCALE_IDENTITY_HEADERS = ("tailscale-user-login", "tailscale-user-name")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RCSL AI Nexus Admin (tailnet)",
        docs_url="/docs",
        openapi_url="/openapi.json",
        debug=False,
        lifespan=admin_lifespan,
    )

    install_error_handlers(app, envelope="admin", auth_mode=settings.auth_mode)
    mount_admin_routers(app)

    # The one line that decides this application's trust model. Without it
    # `current_actor` raises, so an entrance that forgot to choose fails on
    # its first authenticated request rather than defaulting to anything.
    app.dependency_overrides[current_actor] = resolve_tailnet_actor

    return app


app = create_app()
