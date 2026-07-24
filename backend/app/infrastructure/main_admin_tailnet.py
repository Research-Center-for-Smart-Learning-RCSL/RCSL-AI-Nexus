"""Control plane, tailnet entrance.

Identity comes from the `Tailscale-User-Login` header injected by
`tailscale serve`. This application is published on loopback only.

It is a separate ASGI application from the public entrance rather than a
branch inside one, because the two trust models are incompatible: this one
trusts an identity header outright. If the public entrance shared this
socket, a forged `Tailscale-User-Login` would grant administrator access.
Isolation is by socket binding, not by string comparison.
See docs/architecture/security.md section 5.1.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.infrastructure.config import get_settings
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.routers import health

TAILSCALE_IDENTITY_HEADERS = ("tailscale-user-login", "tailscale-user-name")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RCSL AI Nexus Admin (tailnet)",
        docs_url="/docs",
        openapi_url="/openapi.json",
        debug=False,
    )

    install_error_handlers(app, envelope="admin")
    app.include_router(health.router)

    _ = settings
    return app


app = create_app()
