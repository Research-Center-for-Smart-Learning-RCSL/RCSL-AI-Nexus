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
    build_audit,
    build_authorization,
    build_cache,
    build_password_hasher,
    build_password_policy,
    build_secret_box,
    build_session_store,
    build_token_service,
    build_totp,
)
from app.interfaces.http.routers import health, invitations, me, users


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

    # No runtime wiring here yet. `/admin/chat` will reuse RouteChatRequest and
    # will need it, along with the concurrency cap, which protects the hardware
    # rather than the perimeter and so applies to internal traffic too. Built
    # when that router lands, not before: a singleton nothing reads is how the
    # last round of dead configuration started.

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
