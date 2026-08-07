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

from app.adapters.metrics.prometheus import build_metrics
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import dispose_engine, init_engine
from app.infrastructure.di import (
    build_api_key_service,
    build_authorization,
    build_cache,
    build_concurrency_limiter,
    build_runtimes,
)
from app.infrastructure.logging_config import configure_logging
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.middleware.body_limit import BodySizeLimitMiddleware
from app.interfaces.http.middleware.geo_filter import build_geo_filter
from app.interfaces.http.middleware.metrics import MetricsMiddleware
from app.interfaces.http.request_context import RequestContextMiddleware
from app.interfaces.http.routers import chat, health, metrics


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    init_engine(settings)
    # Process-wide singletons live on app.state rather than as module globals,
    # so a test can build an app with different wiring without it leaking.
    app.state.runtimes = build_runtimes(settings)
    app.state.concurrency = build_concurrency_limiter(settings)
    # After the limiter, whose saturation it reports at scrape time.
    app.state.metrics = build_metrics(app.state.concurrency)
    app.state.api_key_service = build_api_key_service(settings)
    app.state.authz = build_authorization()
    app.state.cache = build_cache(settings)
    # Built at startup so a missing GeoLite2 database in production stops the
    # service here rather than silently disabling a documented control.
    app.state.geo_filter = build_geo_filter(settings)
    try:
        yield
    finally:
        app.state.geo_filter.close()
        await app.state.cache.close()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    # Before anything else builds a logger, so no startup line is lost
    # to the WARNING-level fallback handler this replaces.
    configure_logging(settings)

    app = FastAPI(
        title="RCSL AI Nexus Gateway",
        # Schema endpoints are disabled in production: the public API is
        # documented separately rather than by exposing internal shapes.
        docs_url="/docs" if settings.expose_openapi else None,
        openapi_url="/openapi.json" if settings.expose_openapi else None,
        debug=False,
        lifespan=lifespan,
    )

    install_error_handlers(app, envelope="openai")
    # Innermost, and the only stack-level check the gateway has. Everything
    # else here — key authentication, the capability check, the geo filter it
    # applies inline — is a route dependency, and FastAPI reads and parses the
    # body before it resolves dependencies. So this is what stands between an
    # anonymous caller and an arbitrarily large allocation; see
    # middleware/body_limit.py for the measurement that found it.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.gateway_max_body_bytes,
        envelope="openai",
    )
    # No other stack-level perimeter middleware runs here (the gateway applies
    # the geo filter inline in key auth), so /metrics rests on its bearer token
    # alone; see interfaces/http/routers/metrics.py.
    app.add_middleware(MetricsMiddleware)
    # Added last, so it is outermost: every response, including one a rejected
    # middleware builds, passes back through it and gets the X-Request-Id
    # header. The 500 path is the one exception and sets its own; see
    # errors.handle_unanticipated.
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(metrics.router)

    return app


app = create_app()
