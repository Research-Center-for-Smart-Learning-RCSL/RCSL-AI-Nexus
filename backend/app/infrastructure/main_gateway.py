"""Data plane application.

Mounts `/v1/*` only. No admin router is imported here, so there is no code
path from this process to the management API even if it is fully
compromised. The isolation is guaranteed by what is mounted and by socket
binding, not by a path rule in a reverse proxy that one typo could undo.
See docs/architecture/security.md section 1.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.infrastructure.config import get_settings
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.routers import health


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RCSL AI Nexus Gateway",
        # Schema endpoints are disabled in production: the public API is
        # documented separately rather than by exposing internal shapes.
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        debug=False,
    )

    install_error_handlers(app, envelope="openai")
    app.include_router(health.router)

    return app


app = create_app()
