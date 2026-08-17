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

from app.domain.entities.audit import AuditAction
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
    EvaluationRunNotFoundError,
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
    PromptLogNotFoundError,
    PromptTemplateNotFoundError,
    QuotaExceededError,
    RateLimitedError,
    RequestTooLargeError,
    RetentionWindowTooLongError,
    RetentionWindowTooShortError,
    RuntimeCapabilityError,
    RuntimeUnavailableError,
    ServerOverloadedError,
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
from app.interfaces.http.request_context import current_request_id, debug_detail_active

logger = logging.getLogger(__name__)

STATUS_MAP: dict[type[DomainError], int] = {
    ModelNotFoundError: 404,
    NoAvailableModelError: 503,
    AssistantUnavailableError: 503,
    ModelStateConflictError: 409,
    InsufficientMemoryError: 409,
    InvalidModelReferenceError: 400,
    ContextTooLongError: 413,
    RequestTooLargeError: 413,
    QuotaExceededError: 429,
    RateLimitedError: 429,
    CountryNotAllowedError: 403,
    UntrustedProxyError: 400,
    InvalidNodeAddressError: 400,
    RetentionWindowTooShortError: 400,
    PromptLogNotFoundError: 404,
    EvaluationRunNotFoundError: 404,
    RetentionWindowTooLongError: 400,
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
    PromptTemplateNotFoundError: 404,
    DocumentNotFoundError: 404,
    DocumentStateConflictError: 409,
    # 413, not 400: the common rejection is size, and a caller that sees 413
    # knows to send less rather than to send something different.
    UploadRejectedError: 413,
    DocumentParseError: 422,
    RuntimeCapabilityError: 400,
    VectorStoreError: 503,
    ServerOverloadedError: 503,
    # RuntimeTimeoutError and StreamInterruptedError are absent on purpose:
    # they subclass NoAvailableModelError and inherit its 503 through the MRO
    # walk below, so the split stays a split of *codes*, not of statuses.
}

OPENAI_ERROR_TYPES: dict[int, str] = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "conflict_error",
    # 413 was absent until 2026-08-07 and fell through to `api_error`, the value
    # `handle_unanticipated` uses for a 500. So both `context_too_long` and
    # `request_too_large` — the caller's own request being too big, permanent
    # until they send less — announced themselves to every OpenAI client library
    # as a server-side fault, which is the one classification that invites a
    # retry. That is the split-by-remedy rule in `domain/exceptions.py` losing
    # in the last translation before the wire.
    413: "invalid_request_error",
    429: "rate_limit_error",
    503: "service_unavailable",
}

OPENAI_ERROR_TYPE_OVERRIDES: dict[type[DomainError], str] = {
    # Status is the wrong key for this one. 429 carries two conditions whose
    # remedies are opposite — back off and retry, or stop and ask for more
    # budget — and `backend.md` §5 has said since the gateway shipped that
    # clients must branch on the code to tell them apart. The `type` field is
    # the only half of that a client library reads: OpenAI's own error classes
    # are selected from it, and `insufficient_quota` is where they put "this
    # will not succeed by waiting".
    #
    # Sending `rate_limit_error` for an exhausted quota therefore asked every
    # OpenAI-compatible client to do the one thing that could not work. On
    # 2026-08-14 a Codex session did exactly that against key 68953ceb and
    # reported `exceeded retry limit, last status: 429` — a message about its
    # own backoff, naming neither the quota nor the key, to an operator with no
    # way to reach either from it.
    QuotaExceededError: "insufficient_quota",
}


def _status_for(exc: DomainError) -> int:
    for klass in type(exc).__mro__:
        if klass in STATUS_MAP:
            return STATUS_MAP[klass]
    return 500


def _openai_type_for(exc: DomainError, status: int) -> str:
    """Walked over the MRO for the same reason `_status_for` is: a subclass
    added later inherits the classification its parent was given, rather than
    silently falling back to the status map."""
    for klass in type(exc).__mro__:
        if klass in OPENAI_ERROR_TYPE_OVERRIDES:
            return OPENAI_ERROR_TYPE_OVERRIDES[klass]
    return OPENAI_ERROR_TYPES.get(status, "api_error")


def _log(request: Request, exc: DomainError, status: int) -> None:
    """The operator-facing detail goes to the log, never to the response.

    `request_id` is the same value the caller received in `X-Request-Id` and
    in `error.request_id`, which is what makes this line findable from a
    caller's report. `DomainError`'s docstring promised this correlation from
    the start; until 2026-08-05 nothing implemented it.
    """
    logger.warning(
        "domain_error code=%s status=%s path=%s request_id=%s detail=%s",
        exc.code,
        status,
        request.url.path,
        current_request_id(),
        exc.detail,
    )


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
        AuditAction.AUTHZ_DENIED,
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
        # A fixed hour here until 2026-08-14, which was not a rounding error
        # but a wrong model of the window: it trails 24 hours behind the
        # current moment, so the wait after exhausting a quota is anything up
        # to a full day and was an hour only by coincidence. A client that
        # believed the header retried twelve times too early, and the header
        # is the only thing that could have told it otherwise.
        #
        # Omitted rather than guessed when the middleware could not project a
        # recovery time. No header at all leaves a client to its own backoff,
        # which is what a wrong one did anyway, minus the false authority.
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)
    elif isinstance(exc, ServerOverloadedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)

    request_id = current_request_id()

    if envelope == "openai":
        error: dict[str, object] = {
            "type": _openai_type_for(exc, status),
            "code": exc.code,
            "message": exc.public_message,
        }
        if request_id is not None:
            # An extra key inside the envelope; OpenAI client libraries ignore
            # what they do not know. It repeats the X-Request-Id header because
            # bodies get pasted into bug reports and headers do not.
            error["request_id"] = request_id
        if debug_detail_active() and exc.detail:
            # The one condition under which operator-facing detail leaves the
            # process: an administrator opened a time-boxed debug window on
            # this credential. See request_context.grant_debug_detail.
            error["detail"] = exc.detail
        error.update(_context_fields(exc))
        body: dict[str, object] = {"error": error}
    else:
        body = {"code": exc.code, "message": exc.public_message}
        if request_id is not None:
            body["request_id"] = request_id
        if debug_detail_active() and exc.detail:
            body["detail"] = exc.detail
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
        elif fields := _context_fields(exc):
            body["details"] = fields

    return JSONResponse(status_code=status, content=body, headers=headers)


def _context_fields(exc: DomainError) -> dict[str, object]:
    """The figures on a `context_too_long`, for whichever envelope asked.

    Flat inside the OpenAI `error` object and nested under `details` on the
    admin one, because that is where each envelope already puts its extras —
    `request_id` on one, `InsufficientMemoryError`'s two numbers on the other.
    OpenAI client libraries ignore keys they do not know, so the flat placement
    costs a caller nothing and reads correctly when a body is pasted into a
    report.

    See `ContextTooLongError.__init__` for why these leave the process at all
    when `detail` does not.
    """
    if not isinstance(exc, ContextTooLongError):
        return {}
    fields: dict[str, object] = {}
    if exc.estimated is not None:
        fields["estimated"] = exc.estimated
    if exc.limit is not None:
        fields["limit"] = exc.limit
    if exc.composition is not None:
        fields["composition"] = exc.composition
    return fields


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

    validation_handler = (
        _openai_validation_handler if envelope == "openai" else _admin_validation_handler
    )
    app.add_exception_handler(RequestValidationError, validation_handler)

    async def handle_unanticipated(request: Request, exc: Exception) -> JSONResponse:
        """The 500, with an envelope and the request id.

        Until 2026-08-05 this response was the framework's bare
        `Internal Server Error` text — the one non-JSON body the API could
        produce, on exactly the status where a client most needs to degrade
        gracefully, and with nothing the caller could quote to an operator.
        The traceback still goes only to the log; what the caller gets is the
        id that finds it.

        Registered on `Exception`, which Starlette wires into
        `ServerErrorMiddleware` — *outside* `RequestContextMiddleware`, so the
        header added there is absent on this path and is set here instead.
        The contextvar is still readable because the middleware deliberately
        does not reset it on the way out.
        """
        request_id = current_request_id()
        logger.exception("unhandled_error path=%s request_id=%s", request.url.path, request_id)
        if envelope == "openai":
            error: dict[str, object] = {
                "type": "api_error",
                "code": "internal_error",
                "message": "An internal error occurred.",
            }
            if request_id is not None:
                error["request_id"] = request_id
            body: dict[str, object] = {"error": error}
        else:
            body = {"code": "internal_error", "message": "An internal error occurred."}
            if request_id is not None:
                body["request_id"] = request_id
        headers = {"X-Request-Id": request_id} if request_id is not None else None
        return JSONResponse(status_code=500, content=body, headers=headers)

    app.add_exception_handler(Exception, handle_unanticipated)


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
    request_id = current_request_id()
    logger.info("request_validation_failed path=%s request_id=%s", request.url.path, request_id)
    error: dict[str, object] = {
        "type": "invalid_request_error",
        "code": "invalid_request",
        # Pydantic's own summary, which names the field and the rule.
        # It describes the caller's own request, so unlike a
        # `DomainError.detail` there is nothing here to withhold.
        "message": _validation_message(exc),
    }
    if request_id is not None:
        error["request_id"] = request_id
    return JSONResponse(status_code=422, content={"error": error})


async def _admin_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """The same repair on the admin entrances, whose shape is the flat one.

    FastAPI's `{"detail": [...]}` was the last admin response that did not look
    like an admin error: no `code` to branch on and — since the request id
    landed on 2026-08-05 — no `request_id` to quote, which made a validation
    failure the one admin error a caller could not correlate to its log line.

    It cost the operator something concrete rather than only consistency. The
    frontend's `messageFor` reads `body.message`, then `body.detail` *if it is a
    string*; pydantic's is a list, so both fell through and the UI showed
    "Request failed with status 422." — a status number in place of a message
    that had already named the exact field and rule.

    That message is passed through, as on the gateway, and for the same reason:
    it describes the caller's own request, so unlike a `DomainError.detail`
    there is nothing in it to withhold.
    """
    if not isinstance(exc, RequestValidationError):
        raise exc
    request_id = current_request_id()
    logger.info("request_validation_failed path=%s request_id=%s", request.url.path, request_id)
    body: dict[str, object] = {
        "code": "invalid_request",
        "message": _validation_message(exc),
    }
    if request_id is not None:
        body["request_id"] = request_id
    return JSONResponse(status_code=422, content=body)


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        # `body` heads every location on a request body; dropping it leaves the
        # field path the caller actually wrote.
        location = ".".join(str(p) for p in error.get("loc", ()) if p != "body")
        message = error.get("msg", "invalid")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "request failed validation"
