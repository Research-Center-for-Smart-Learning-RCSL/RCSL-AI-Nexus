"""Domain error to HTTP mapping.

Registered once per application. Routers do not write their own try/except
blocks for domain errors, which is what keeps the "no internal detail in
responses" rule from depending on every handler remembering it.

Two envelope shapes exist: the gateway follows the OpenAI error format so
existing clients parse it, and the admin API uses a plainer shape.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    ContextTooLongError,
    CountryNotAllowedError,
    CsrfValidationError,
    DomainError,
    InsufficientMemoryError,
    InvalidCredentialsError,
    InvalidModelReferenceError,
    InvalidNodeAddressError,
    InvalidTotpError,
    InvitationInvalidError,
    ModelNotFoundError,
    ModelStateConflictError,
    NoAvailableModelError,
    NotAuthenticatedError,
    NotAuthorizedError,
    QuotaExceededError,
    RateLimitedError,
    TotpEnrolmentExpiredError,
    TotpRequiredError,
    UntrustedProxyError,
    UserAlreadyExistsError,
    WeakPasswordError,
)

logger = logging.getLogger(__name__)

STATUS_MAP: dict[type[DomainError], int] = {
    ModelNotFoundError: 404,
    NoAvailableModelError: 503,
    ModelStateConflictError: 409,
    InsufficientMemoryError: 409,
    InvalidModelReferenceError: 400,
    ContextTooLongError: 413,
    QuotaExceededError: 429,
    RateLimitedError: 429,
    CountryNotAllowedError: 403,
    UntrustedProxyError: 400,
    InvalidNodeAddressError: 400,
    NotAuthenticatedError: 401,
    NotAuthorizedError: 403,
    InvalidCredentialsError: 401,
    TotpRequiredError: 401,
    InvalidTotpError: 401,
    InvitationInvalidError: 400,
    WeakPasswordError: 400,
    UserAlreadyExistsError: 409,
    TotpEnrolmentExpiredError: 400,
    CsrfValidationError: 403,
}

OPENAI_ERROR_TYPES: dict[int, str] = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "conflict_error",
    429: "rate_limit_error",
    503: "service_unavailable",
}


def _status_for(exc: DomainError) -> int:
    for klass in type(exc).__mro__:
        if klass in STATUS_MAP:
            return STATUS_MAP[klass]  # type: ignore[index]
    return 500


def _log(request: Request, exc: DomainError, status: int) -> None:
    """The operator-facing detail goes to the log, never to the response."""
    logger.warning(
        "domain_error code=%s status=%s path=%s detail=%s",
        exc.code,
        status,
        request.url.path,
        exc.detail,
    )


def error_response(
    exc: DomainError, *, envelope: str = "admin", auth_mode: str | None = None
) -> JSONResponse:
    """Render a domain error, independently of the exception handler.

    Middleware needs this. Starlette builds its stack as
    `ServerErrorMiddleware -> user middleware -> ExceptionMiddleware`, so a
    `DomainError` raised inside a middleware never reaches the handler
    registered below and surfaces as a bare 500. Middleware that rejects a
    request therefore returns this rather than raising.
    """
    status = _status_for(exc)

    headers: dict[str, str] = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)
    elif isinstance(exc, QuotaExceededError):
        headers["Retry-After"] = "3600"

    if envelope == "openai":
        body: dict[str, object] = {
            "error": {
                "type": OPENAI_ERROR_TYPES.get(status, "api_error"),
                "code": exc.code,
                "message": exc.public_message,
            }
        }
    else:
        body = {"code": exc.code, "message": exc.public_message}
        if status == 401 and auth_mode is not None:
            body["auth_mode"] = auth_mode
        if isinstance(exc, InsufficientMemoryError):
            body["details"] = {
                "required_gb": exc.required_gb,
                "available_gb": exc.available_gb,
            }
        elif isinstance(exc, WeakPasswordError):
            body["details"] = {"reason": exc.reason}

    return JSONResponse(status_code=status, content=body, headers=headers)


def install_error_handlers(
    app: FastAPI, *, envelope: str = "admin", auth_mode: str | None = None
) -> None:
    """`auth_mode` is echoed on 401 bodies only.

    The frontend is one build serving two entrances and decides what a 401
    means from it: "your Tailscale connection dropped" on the tailnet, "go to
    the login screen" on the public entrance. It normally learns this from
    `/admin/me`, which is exactly the call that 401s when there is no session,
    so without this the UI has to guess at the one moment it most needs to be
    right. Nothing here is a secret: the entrance is evident from its hostname.
    """

    async def handle(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, DomainError):
            # Registration guarantees this, but an `assert` would vanish under
            # python -O and turn a wiring mistake into a confusing 500.
            raise exc
        _log(request, exc, _status_for(exc))
        return error_response(exc, envelope=envelope, auth_mode=auth_mode)

    handler: Callable[[Request, Exception], Awaitable[JSONResponse]] = handle
    app.add_exception_handler(DomainError, handler)
