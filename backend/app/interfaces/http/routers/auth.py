"""Sign in and sign out on the public entrance.

Two steps, not one. Password verification returns a **challenge**, not a
session: it names an account whose password was correct and carries no
privilege of its own. Only the second factor produces a session. Splitting
them is what lets both be rate limited independently, and what stops a
correct password alone from being worth anything.

See docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.adapters.session.session_store import SessionStore
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.domain.exceptions import InvalidCredentialsError
from app.domain.ports.infrastructure_ports import CachePort
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import (
    build_authenticate_local,
    get_cache,
    get_session_store,
)
from app.interfaces.http.middleware.client_ip import resolve_client_ip
from app.interfaces.http.middleware.csrf import issue_csrf_cookie
from app.interfaces.http.schemas.admin_schemas import (
    LoginChallengeResponse,
    LoginRequest,
    RecoveryCodeLoginRequest,
    TotpLoginRequest,
)
from app.shared.clock import SystemClock

router = APIRouter(prefix="/auth", tags=["auth"])

CHALLENGE_PREFIX = "login_challenge:"
CHALLENGE_TTL_SECONDS = 300
"""Long enough to open an authenticator app, short enough that an abandoned
first step does not leave a usable handle lying in the cache."""


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    auth: Annotated[AuthenticateLocal, Depends(build_authenticate_local)],
    cache: Annotated[CachePort, Depends(get_cache)],
) -> LoginChallengeResponse:
    result = await auth.verify_password(
        payload.login, payload.password, client_ip=_client_ip(request)
    )

    challenge = secrets.token_urlsafe(32)
    await cache.set(
        f"{CHALLENGE_PREFIX}{challenge}", result.user_id, ttl_seconds=CHALLENGE_TTL_SECONDS
    )
    return LoginChallengeResponse(challenge=challenge)


@router.post("/login/totp", status_code=204)
async def login_totp(
    payload: TotpLoginRequest,
    request: Request,
    auth: Annotated[AuthenticateLocal, Depends(build_authenticate_local)],
    cache: Annotated[CachePort, Depends(get_cache)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    user_id = await _consume_challenge(cache, payload.challenge)
    user = await auth.verify_totp(user_id, payload.code, client_ip=_client_ip(request))
    return await _establish_session(user.id, sessions, settings)


@router.post("/login/recovery-code", status_code=204)
async def login_recovery_code(
    payload: RecoveryCodeLoginRequest,
    request: Request,
    auth: Annotated[AuthenticateLocal, Depends(build_authenticate_local)],
    cache: Annotated[CachePort, Depends(get_cache)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    user_id = await _consume_challenge(cache, payload.challenge)
    user = await auth.verify_recovery_code(
        user_id, payload.recovery_code, client_ip=_client_ip(request)
    )
    return await _establish_session(user.id, sessions, settings)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Deliberately does not depend on a valid session.

    Signing out has to work when the session has already expired or been
    invalidated elsewhere, and returning 401 there would leave the cookie in
    place on a shared machine. The CSRF middleware still gates the request.
    """
    session_id = request.cookies.get(settings.effective_session_cookie)
    if session_id:
        await sessions.destroy(session_id)

    response = Response(status_code=204)
    _clear_cookie(response, settings.effective_session_cookie, settings)
    _clear_cookie(response, settings.effective_csrf_cookie, settings)
    return response


async def _consume_challenge(cache: CachePort, challenge: str) -> str:
    """Single use: read then delete.

    A challenge that survived its use would let a captured first step be
    replayed against the second for as long as its TTL lasted.
    """
    key = f"{CHALLENGE_PREFIX}{challenge}"
    user_id = await cache.get(key)
    await cache.delete(key)

    if not user_id:
        # Same error as a wrong password. An expired challenge and a forged one
        # are not worth distinguishing to the caller.
        raise InvalidCredentialsError(detail="unknown or expired login challenge")
    return user_id


async def _establish_session(user_id: str, sessions: SessionStore, settings: Settings) -> Response:
    """Issue the session and bind CSRF to it.

    The identifier is new, never one the client presented, so there is nothing
    for a fixation attempt to plant beforehand. The CSRF cookie is replaced
    with the session's own token, which is what lets `identity.py` compare the
    header against a value the client was never in a position to choose.
    """
    data = await sessions.create(user_id, SystemClock().now())

    response = Response(status_code=204)
    response.set_cookie(
        settings.effective_session_cookie,
        data.session_id,
        max_age=settings.session_absolute_ttl_seconds,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    issue_csrf_cookie(
        response,
        data.csrf_token,
        cookie_name=settings.effective_csrf_cookie,
        secure=settings.cookie_secure,
        max_age=settings.session_absolute_ttl_seconds,
    )
    return response


def _clear_cookie(response: Response, name: str, settings: Settings) -> None:
    # Attributes must match the ones the cookie was set with, or the browser
    # treats it as a different cookie and leaves the original in place.
    response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


def _client_ip(request: Request) -> str:
    return str(resolve_client_ip(request))
