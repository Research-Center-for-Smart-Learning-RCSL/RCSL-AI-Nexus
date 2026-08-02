"""Resolving who is calling an admin entrance.

`current_actor` is a placeholder that raises. Each application replaces it
through `dependency_overrides` with the resolver for its own trust model, and
an application that forgets to do so fails on the first authenticated request
rather than falling back to something permissive. That is the point of the
arrangement: a router cannot be given the wrong resolver by accident, because
it never names one.

The two resolvers must never coexist in one process. Isolation comes from the
socket binding described in docs/architecture/security.md section 5.1; this
module is what makes the difference structural inside the process as well.
"""

from __future__ import annotations

from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, Request

from app.adapters.persistence.repositories import PostgresUserRepository
from app.adapters.session.session_store import SessionData, SessionStore
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.domain.entities.actor import Actor
from app.domain.entities.user import User
from app.domain.exceptions import CsrfValidationError, NotAuthenticatedError
from app.domain.ports.security_ports import AuthorizationPort
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import (
    build_bootstrap_first_admin,
    current_actor,
    current_session,
    get_authorization,
    get_session_store,
    get_user_repository,
)
from app.interfaces.http.request_actor import remember_actor
from app.shared.clock import SystemClock

# `current_actor` and `current_session` are defined in di.py (so the tenant-
# scoped repository builders can depend on the actor without a circular import)
# and re-exported here, because routers and the entrance apps import them from
# this module. See app/infrastructure/di.py.
__all__ = [
    "current_actor",
    "current_session",
    "resolve_session_actor",
    "resolve_tailnet_actor",
    "session_from_request",
]

TAILSCALE_LOGIN_HEADER = "tailscale-user-login"
TAILSCALE_NAME_HEADER = "tailscale-user-name"

SESSION_STATE_KEY = "nexus_session"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def resolve_tailnet_actor(
    request: Request,
    users: Annotated[PostgresUserRepository, Depends(get_user_repository)],
    bootstrap: Annotated[BootstrapFirstAdmin, Depends(build_bootstrap_first_admin)],
    authz: Annotated[AuthorizationPort, Depends(get_authorization)],
) -> Actor:
    """Identity from the header `tailscale serve` injects.

    The header is trusted outright, which is only defensible because this
    application is published on loopback and reached solely through
    `tailscale serve`. Nothing here validates it, and nothing can: a forged
    header is indistinguishable from a real one at this layer. The control is
    that no forged header can arrive.

    **Passing this does not mean administrator.** The header says who; the
    `users` table says what they may do, and an identity with no row is
    refused. Roles are owned by the platform, not by the identity source.
    """
    settings = get_settings()
    login, display_name = _presented_identity(request, settings)

    if not login:
        raise NotAuthenticatedError(detail="no Tailscale identity header")

    user = await users.get_by_tailscale_login(login)
    if user is None:
        # Applies only while the users table is empty, and only here.
        user = await bootstrap.claim(login, display_name)

    if user is None:
        raise NotAuthenticatedError(detail=f"tailnet login {login} has no account")

    return remember_actor(
        request,
        _actor_for(user, source="dev" if settings.auth_mode == "dev" else "tailnet", authz=authz),
    )


async def resolve_session_actor(
    request: Request,
    users: Annotated[PostgresUserRepository, Depends(get_user_repository)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    authz: Annotated[AuthorizationPort, Depends(get_authorization)],
) -> Actor:
    """Identity from a server-side session, established by password and TOTP."""
    settings = get_settings()
    session_id = request.cookies.get(settings.effective_session_cookie)
    if not session_id:
        raise NotAuthenticatedError(detail="no session cookie")

    now = SystemClock().now()
    data = await sessions.read(session_id, now)
    if data is None:
        raise NotAuthenticatedError(detail="session unknown, expired, or superseded")

    user = await users.get(data.user_id)
    if user is None or user.disabled_at is not None:
        # The account went away or was disabled while the session lived. Drop
        # the session rather than only refusing this request, so a disabled
        # account stops costing a lookup on every retry.
        await sessions.destroy(session_id)
        raise NotAuthenticatedError(detail=f"session for unusable user {data.user_id}")

    _assert_csrf_bound_to_session(request, data, settings)

    setattr(request.state, SESSION_STATE_KEY, data)
    return remember_actor(request, _actor_for(user, source="local", authz=authz))


def session_from_request(request: Request) -> SessionData | None:
    return getattr(request.state, SESSION_STATE_KEY, None)


def _presented_identity(request: Request, settings: Settings) -> tuple[str, str]:
    if settings.auth_mode == "dev":
        # Substituting the header, not the outcome. Everything downstream,
        # including bootstrap, runs exactly as it does in production.
        return settings.dev_tailnet_login.strip().lower(), "Development"

    return (
        request.headers.get(TAILSCALE_LOGIN_HEADER, "").strip().lower(),
        request.headers.get(TAILSCALE_NAME_HEADER, "").strip(),
    )


def _actor_for(user: User, *, source: str, authz: AuthorizationPort) -> Actor:
    if user.disabled_at is not None:
        raise NotAuthenticatedError(detail=f"disabled user {user.id}")

    return Actor(
        id=user.id,
        display=user.login,
        role=user.role,
        source=source,  # type: ignore[arg-type]
        scopes=authz.scopes_for(user.role.value),
        tenant_id=user.tenant_id,
    )


def _assert_csrf_bound_to_session(request: Request, data: SessionData, settings: Settings) -> None:
    """Second half of the CSRF defence, and the half the middleware cannot do.

    The middleware compares the cookie against the header, which stops an
    ordinary cross-site form post because the attacker cannot read the cookie.
    It does not stop someone who can *write* cookies for this domain: a
    subdomain takeover or an XSS on a sibling host lets them set both halves to
    a value they chose, and the double-submit then agrees with itself.

    Comparing against the value held server-side in the session closes that,
    because the session's token was never sent anywhere they could read.
    """
    if request.method in SAFE_METHODS:
        return

    presented = request.headers.get(settings.csrf_header_name, "")
    # utf-8 encodings, so a non-ASCII header (Starlette decodes headers as
    # latin-1) does not make compare_digest raise TypeError and turn a 403 into
    # a 500. A session token is url-safe base64, hence pure ASCII.
    if not compare_digest(
        presented.encode("utf-8", "ignore"), data.csrf_token.encode("utf-8", "ignore")
    ):
        raise CsrfValidationError(detail=f"header does not match session {data.session_id[:8]}")
