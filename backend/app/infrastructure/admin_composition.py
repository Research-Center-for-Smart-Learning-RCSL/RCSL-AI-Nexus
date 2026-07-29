"""What the two admin entrances share.

Both mount the same routers and build the same singletons; they differ only in
how a caller's identity is established and in what protects the request. That
difference is expressed as a dependency override rather than as a branch,
because a branch is a string comparison and this project's rule is that the
isolation between the entrances is structural.

See docs/architecture/security.md section 5.1 and
interfaces/http/middleware/identity.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.adapters.metrics.prometheus import build_metrics
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import dispose_engine, init_engine
from app.infrastructure.di import (
    build_api_key_service,
    build_audit,
    build_authorization,
    build_cache,
    build_concurrency_limiter,
    build_job_progress,
    build_password_hasher,
    build_password_policy,
    build_runtimes,
    build_secret_box,
    build_session_store,
    build_token_service,
    build_totp,
)
from app.infrastructure.heartbeat import run_heartbeat
from app.interfaces.http.middleware.geo_filter import build_geo_filter
from app.interfaces.http.routers import (
    admin_chat,
    api_keys,
    assistant,
    dashboard,
    gateway_info,
    health,
    invitations,
    logs,
    me,
    metrics,
    models,
    nodes,
    routing_policies,
    tenants,
    usage,
    users,
)


@asynccontextmanager
async def admin_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    init_engine(settings)

    app.state.authz = build_authorization()
    app.state.cache = build_cache(settings)
    app.state.sessions = build_session_store(settings, app.state.cache)
    app.state.audit = build_audit()

    # Singletons, and each for a reason worth keeping: the hasher owns the
    # semaphore that bounds how much memory concurrent login attempts occupy,
    # and the policy holds zxcvbn's frequency dictionary, which is expensive
    # to load and pointless to load twice.
    app.state.hasher = build_password_hasher()
    app.state.totp = build_totp()
    app.state.secret_box = build_secret_box(settings)
    app.state.password_policy = build_password_policy()
    app.state.tokens = build_token_service()

    # `/admin/chat` reuses RouteChatRequest, and the model lifecycle endpoints
    # talk to the same adapters, so the runtime wiring exists here too. The
    # concurrency cap comes with it deliberately: it protects the hardware
    # rather than the perimeter, so internal traffic is subject to it exactly
    # as public traffic is.
    app.state.runtimes = build_runtimes(settings)
    app.state.concurrency = build_concurrency_limiter(settings)
    # After the limiter, whose saturation it reports; `/admin/chat` runs inference
    # here too, so the slot gauge is meaningful on both admin entrances.
    app.state.metrics = build_metrics(app.state.concurrency)
    app.state.api_key_service = build_api_key_service(settings)
    app.state.jobs = build_job_progress(app.state.cache)
    # Built at startup so a missing GeoLite2 database in production stops the
    # service here rather than silently disabling a documented control.
    app.state.geo_filter = build_geo_filter(settings)

    # Nothing is written here at startup. The one row no endpoint creates, the
    # compute node, is provisioned by the `migrate` service; see
    # infrastructure/provision.py for why startup is the wrong place for it.

    # The node status heartbeat. It runs here rather than in the gateway because
    # §6 forbids the gateway writing `nodes`; it sleeps before its first sweep,
    # so a lifespan that opens and closes quickly (every test) cancels it before
    # it touches the database. Disabled by a non-positive interval.
    heartbeat: asyncio.Task[None] | None = None
    if settings.node_heartbeat_interval_seconds > 0:
        heartbeat = asyncio.create_task(
            run_heartbeat(app, settings.node_heartbeat_interval_seconds)
        )

    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        app.state.geo_filter.close()
        await app.state.cache.close()
        await dispose_engine()


ADMIN_PREFIX = "/admin"
"""Every management route lives under this, and the reason is the Next.js
rewrite: `frontend/next.config.js` forwards `/admin/:path*` to
`${ADMIN_API_URL}/admin/:path*`, **keeping** the prefix, and
`api-client.ts` prepends `/admin` to every path. Mounting at the root meant
the browser asked for `/admin/me` and got a 404 from a service whose route
was `/me`, so nothing in the UI worked at all.

The tests missed it because they call the ASGI app directly. `test_route_
prefix.py` now pins the contract rather than the handlers.

Health is deliberately outside it: `/healthz` and `/readyz` are probed by
Compose and by the reverse proxy, neither of which goes through the rewrite.
"""


def mount_admin_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    # Root-level like health, not under /admin: Prometheus scrapes it directly
    # over the internal metrics network, not through the frontend rewrite.
    app.include_router(metrics.router)

    for router in (
        me.router,
        users.router,
        invitations.router,
        models.router,
        nodes.router,
        tenants.router,
        api_keys.router,
        gateway_info.router,
        routing_policies.router,
        dashboard.router,
        usage.router,
        logs.router,
        admin_chat.router,
        # Admin entrances only, and deliberately not mounted on the gateway:
        # `assist` is routable but not issuable, so no API key can name it, and
        # the endpoint that serves it should not exist where only API keys call.
        assistant.router,
    ):
        app.include_router(router, prefix=ADMIN_PREFIX)
