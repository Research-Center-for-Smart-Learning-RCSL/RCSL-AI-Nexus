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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
from app.infrastructure.local_node import ensure_local_node
from app.interfaces.http.routers import (
    admin_chat,
    api_keys,
    dashboard,
    health,
    invitations,
    me,
    models,
    routing_policies,
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
    app.state.api_key_service = build_api_key_service(settings)
    app.state.jobs = build_job_progress(app.state.cache)

    # The model registry needs a node to attach models to, and Phase 1 has no
    # endpoint that creates one: see infrastructure/local_node.py.
    await ensure_local_node(settings)

    try:
        yield
    finally:
        await app.state.cache.close()
        await dispose_engine()


def mount_admin_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(users.router)
    app.include_router(invitations.router)
    app.include_router(models.router)
    app.include_router(api_keys.router)
    app.include_router(routing_policies.router)
    app.include_router(dashboard.router)
    app.include_router(admin_chat.router)
