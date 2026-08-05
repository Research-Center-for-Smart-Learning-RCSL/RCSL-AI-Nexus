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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    AssistantUnavailableError,
    CollectionNotFoundError,
    ContextTooLongError,
    CountryNotAllowedError,
    CsrfValidationError,
    DocumentNotFoundError,
    DocumentParseError,
    DocumentStateConflictError,
    DomainError,
    InsufficientMemoryError,
    InvalidCidrError,
    InvalidCredentialsError,
    InvalidModelReferenceError,
    InvalidNodeAddressError,
    InvalidTotpError,
    InvitationInvalidError,
    LastAdministratorError,
    ModelNotFoundError,
    ModelStateConflictError,
    NoAvailableModelError,
    NodeNotFoundError,
    NoLocalCredentialsError,
    NotAuthenticatedError,
    NotAuthorizedError,
    QuotaExceededError,
    RateLimitedError,
    RetentionWindowTooShortError,
    RuntimeCapabilityError,
    RuntimeUnavailableError,
    TotpEnrolmentExpiredError,
    TotpRequiredError,
    UntrustedProxyError,
    UploadRejectedError,
    UserAlreadyExistsError,
    UserNotFoundError,
    VectorStoreError,
    WeakPasswordError,
)
from app.interfaces.http.request_actor import actor_from_request

logger = logging.getLogger(__name__)

STATUS_MAP: dict[type[DomainError], int] = {
    ModelNotFoundError: 404,
    NoAvailableModelError: 503,
    AssistantUnavailableError: 503,
    ModelStateConflictError: 409,
    InsufficientMemoryError: 409,
    InvalidModelReferenceError: 400,
    ContextTooLongError: 413,
    QuotaExceededError: 429,
    RateLimitedError: 429,
    CountryNotAllowedError: 403,
    UntrustedProxyError: 400,
    InvalidNodeAddressError: 400,
    RetentionWindowTooShortError: 400,
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
    NodeNotFoundError: 404,
    RuntimeUnavailableError: 400,
    InvalidCidrError: 400,
    UserNotFoundError: 404,
    LastAdministratorError: 409,
    NoLocalCredentialsError: 409,
    CollectionNotFoundError: 404,
    DocumentNotFoundError: 404,
    DocumentStateConflictError: 409,
    # 413, not 400: the common rejection is size, and a caller that sees 413
    # knows to send less rather than to send something different.
    UploadRejectedError: 413,
    DocumentParseError: 422,
    RuntimeCapabilityError: 400,
    VectorStoreError: 503,
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
            return STATUS_MAP[klass]
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


AUTHZ_DENIED = "authz.denied"


async def _audit_refusal(request: Request, exc: NotAuthorizedError) -> None:
    """Record an authorization failure, from the one place none can bypass.

    Section 12 requires these and nothing recorded them until 2026-08-02. The
    handler is the right place precisely because it is not a decision point:
    every `NotAuthorizedError` from every use case arrives here, so a new use
    case cannot forget, and a future path that raises without a `require` is
    still seen. Putting it in `AuthorizationPort.require` would be closer to
    the decision but would make that port async at seventy call sites, and
    would still miss the refusals use cases raise directly — an administrator
    changing their own role, a key that does not exist.

    **The gateway does not audit these, and that is deliberate.** Its database
    account may INSERT into `usage_records` and nothing else (section 6), so a
    row here would fail and be logged as a failure on every data-plane 403.
    Granting it `audit_log` would let a compromised gateway write into the
    record that exists to describe the compromise. Its refusals — a key using a
    capability it was not issued for — stay in the application log, and the
    absence is recorded in section 12 rather than hidden here. In practice the
    gateway has no `audit` on its app state, so this returns early.

    Best-effort by construction: `PostgresAudit.record` already swallows and
    logs its own failures, so a refused request cannot become a 500 because the
    audit write failed.
    """
    audit = getattr(request.app.state, "audit", None)
    actor = actor_from_request(request)
    if audit is None or actor is None:
        return

    await audit.record(
        actor,
        AUTHZ_DENIED,
        # The path, not the resource id: this says what was reached for, and
        # the handler cannot know which path parameter was the subject.
        target=request.url.path,
        outcome="denied",
        # `exc.detail` names the missing scope and is operator-facing; it never
        # reaches the response body. Method included because a read and a write
        # refused on the same path are different attempts.
        detail={"method": request.method, "reason": exc.detail or ""},
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
        elif isinstance(exc, UploadRejectedError) and exc.public_detail:
            # The one detail string that goes outward, and it describes the
            # caller's own file: an operator who is told only "this file cannot
            # be accepted" has no way to tell a size limit from a type one.
            body["details"] = {"reason": exc.public_detail}

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
        if isinstance(exc, NotAuthorizedError):
            await _audit_refusal(request, exc)
        return error_response(exc, envelope=envelope, auth_mode=auth_mode)

    handler: Callable[[Request, Exception], Awaitable[JSONResponse]] = handle
    app.add_exception_handler(DomainError, handler)

    if envelope == "openai":
        app.add_exception_handler(RequestValidationError, _openai_validation_handler)


async def _openai_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """A malformed request, in the envelope the caller's library parses.

    FastAPI answers a validation failure with `{"detail": [...]}`, which is its
    own shape and not OpenAI's. Every OpenAI client library reads
    `error.message`, so on the gateway that default arrived as a 422 whose body
    told the caller nothing their code could surface — and it is the response a
    caller gets while they are still getting the request right, which is
    exactly when a legible message is worth most.

    422 is kept rather than rewritten to OpenAI's 400. It is what FastAPI has
    always returned here, the error type says `invalid_request_error` either
    way, and a client branching on the status still treats 4xx as its own
    problem.
    """
    if not isinstance(exc, RequestValidationError):
        raise exc
    logger.info("request_validation_failed path=%s", request.url.path)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_request",
                # Pydantic's own summary, which names the field and the rule.
                # It describes the caller's own request, so unlike a
                # `DomainError.detail` there is nothing here to withhold.
                "message": _validation_message(exc),
            }
        },
    )


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        # `body` heads every location on a request body; dropping it leaves the
        # field path the caller actually wrote.
        location = ".".join(str(p) for p in error.get("loc", ()) if p != "body")
        message = error.get("msg", "invalid")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "request failed validation"
