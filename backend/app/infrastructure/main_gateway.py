"""Data plane application.

Mounts `/v1/*` only. No admin router is imported here, so there is no code
path from this process to the management API even if it is fully compromised.
The isolation is guaranteed by what is mounted and by socket binding, not by a
path rule in a reverse proxy that one typo could undo.
See docs/architecture/security.md section 1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import dispose_engine, init_engine
from app.infrastructure.di import (
    build_api_key_service,
    build_authorization,
    build_cache,
    build_concurrency_limiter,
    build_runtimes,
)
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.routers import chat, health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    init_engine(settings)
    # Process-wide singletons live on app.state rather than as module globals,
    # so a test can build an app with different wiring without it leaking.
    app.state.runtimes = build_runtimes(settings)
    app.state.concurrency = build_concurrency_limiter(settings)
    app.state.api_key_service = build_api_key_service(settings)
    app.state.authz = build_authorization()
    app.state.cache = build_cache(settings)
    try:
        yield
    finally:
        await app.state.cache.close()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RCSL AI Nexus Gateway",
        # Schema endpoints are disabled in production: the public API is
        # documented separately rather than by exposing internal shapes.
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        debug=False,
        lifespan=lifespan,
    )

    install_error_handlers(app, envelope="openai")
    app.include_router(health.router)
    app.include_router(chat.router)

    return app


app = create_app()
