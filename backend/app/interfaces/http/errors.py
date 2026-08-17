"""Domain error to HTTP mapping.

Registered once per application. Routers do not write their own try/except
blocks for domain errors, which is what keeps the "no internal detail in
responses" rule from depending on every handler remembering it.

Two envelope shapes exist: the gateway follows the OpenAI error format so
existing clients parse it, and the admin API uses a plainer shape.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.entities.audit import AuditAction
from app.domain.entities.refusal import Refusal
from app.domain.exceptions import (
    ApiKeyLifetimeError,
    AssistantUnavailableError,
    CapabilityNotIssuedError,
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
    StateConflictError,
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
    StateConflictError: 409,
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


def _route_path(request: Request) -> str:
    """The route as declared, not the URL as sent, wherever routing got that far.

    `/admin/api-keys/{key_id}` rather than `/admin/api-keys/68953ceb…`. Two
    reasons, and the second is the one that decided it. A thousand refusals on
    one endpoint group together instead of scattering by id, which is what makes
    "this endpoint has been refusing all afternoon" visible. And a path
    parameter is a value the caller chose: storing the template keeps this table
    to what the platform said rather than what the caller sent.

    The route's own `path` is not the whole path — routers are included under a
    prefix, and what `scope["route"]` carries is the inner route's spelling,
    `/api-keys/{key_id}` for a request to `/admin/api-keys/<id>`. So the prefix
    is taken from the request and the tail from the template, by position.

    **Substituting the parameter values into the path instead does not work,
    and it is worth saying why, because it looks like it does.** The values are
    caller-chosen, so a value that also appears earlier in the path templates
    the wrong segment: `GET /admin/users/admin` with `user_id="admin"` stored
    itself as `/{user_id}/users/admin`, and `key_id="keys"` turned
    `/admin/api-keys/keys` into `/admin/api-{key_id}/keys`. Any caller could
    provoke a row that named neither the route nor their request.

    Falls back to the literal path when nothing matched, which is a refusal
    raised before or during routing — a body over the byte limit, a country
    block, a request to a path that does not exist.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    path = request.url.path
    if not isinstance(template, str) or not template:
        return path
    tail = [segment for segment in template.split("/") if segment]
    sent = [segment for segment in path.split("/") if segment]
    if len(sent) < len(tail):
        # Nothing sensible to align; the literal path is still true.
        return path
    return "/" + "/".join([*sent[: len(sent) - len(tail)], *tail])


INTERNAL_ERROR_CODE = "internal_error"
INTERNAL_ERROR_MESSAGE = "An internal error occurred."


async def _record_refusal(
    request: Request,
    *,
    code: str,
    status: int,
    message: str,
    figures: dict[str, object],
    surface: str,
) -> None:
    """Keep the refusal where the caller who provoked it can read it back.

    **The handler is the write point, and that is a departure from the shape
    this feature was specified in.** The plan was a row written in the same
    `finally` that records usage, so that one write point served all three
    entrances the way `prompt_logs` does. That works for the inference path and
    only for it: the `409` that cost an operator an evening on 2026-08-17 was an
    API key's expiry being refused on the admin surface, which never reaches
    `RouteChatRequest` at all. Storing every `DomainError` means writing from
    the one place every `DomainError` already passes through, and this is it.

    **Only refusals with an identified caller are kept.** The feature exists so
    that a caller can read their own; an anonymous refusal has no such reader,
    and it would be a row written at whatever rate an unauthenticated client
    chooses to provoke one. The identity-plane refusals that matter — a failed
    sign-in, an authorization denial, a recovery code replayed — are already
    recorded in `audit_log` by §12, which is the table for events about who
    somebody is rather than about what they sent.

    Best-effort twice over: the writer swallows its own failures, and this
    returns quietly when no writer is wired. A deployment that has not run the
    migration still answers its callers.
    """
    writer = getattr(request.app.state, "refusals", None)
    actor = actor_from_request(request)
    if writer is None or actor is None:
        return
    await writer.record(
        Refusal(
            id=str(uuid.uuid4()),
            at=datetime.now(UTC),
            code=code,
            status=status,
            actor_id=actor.id,
            actor_display=actor.display,
            api_key_id=actor.api_key_id,
            surface=surface,
            method=request.method,
            path=_route_path(request),
            request_id=current_request_id(),
            message=message,
            figures=figures,
            tenant_id=actor.tenant_id,
        )
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
        # The same figures the admin envelope carries and the same ones stored,
        # from the one function that decides what may reach a caller. It was
        # `_context_fields` here until 2026-08-18, which meant the gateway's
        # stored refusals could carry a figure its responses had not — and "a
        # row is a copy of the answer you already had" is the whole of why the
        # table is safe to show its own subject. Flattened rather than nested,
        # as the request id above is: OpenAI client libraries ignore keys they
        # do not know, so the placement costs a caller nothing.
        error.update(public_details(exc))
        body: dict[str, object] = {"error": error}
    else:
        body = {"code": exc.code, "message": exc.public_message}
        if request_id is not None:
            body["request_id"] = request_id
        if debug_detail_active() and exc.detail:
            body["detail"] = exc.detail
        if status == 401 and auth_mode is not None:
            body["auth_mode"] = auth_mode
        if fields := public_details(exc):
            body["details"] = fields

    return JSONResponse(status_code=status, content=body, headers=headers)


def public_details(exc: DomainError) -> dict[str, object]:
    """Every figure this error is allowed to hand its caller.

    One function because there are now two readers and they must not disagree:
    the response body renders it, and `refusals` stores it. A refusal row is a
    second copy of what the caller was told, and the only way to keep that claim
    true is for both copies to be built here.

    Nothing operator-facing passes through. `detail` is absent by construction —
    it is not read in this function at all — and so is the model's alias, which
    `NoAvailableModelError` and `ContextTooLongError` are both careful never to
    put in a figure.

    The upload case is the one detail string that does go outward, and it goes
    outward because it describes the caller's own file: an operator told only
    "this file cannot be accepted" has no way to tell a size limit from a type
    one.
    """
    if isinstance(exc, InsufficientMemoryError):
        return {"required_gb": exc.required_gb, "available_gb": exc.available_gb}
    if isinstance(exc, ApiKeyLifetimeError):
        # A field as well as a sentence, and it was only a sentence until
        # 2026-08-18. This is the refusal that cost an operator an evening: they
        # saw a save fail with no subject immediately after editing a capability
        # list, and read it as the capability edit being rejected. A published
        # policy is not inventory — the same ground `limit` reaches a caller on.
        return {"maximum_days": exc.maximum_days}
    if isinstance(exc, CapabilityNotIssuedError):
        # The capability they sent, and the list `GET /v1/models` would return
        # the same key. Both were already in the message; as fields they are
        # something a client can branch on rather than parse.
        return {"capability": exc.capability, "available": list(exc.available)}
    if isinstance(exc, WeakPasswordError):
        return {"reason": exc.reason}
    if isinstance(exc, UploadRejectedError) and exc.public_detail:
        return {"reason": exc.public_detail}
    fields = _context_fields(exc)
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, int):
        # Carried as a figure as well as a header. A caller reading their own
        # refusals a day later has no headers, and "how long was I told to
        # wait" is exactly the question a 429 in that list raises.
        fields["retry_after_seconds"] = retry_after
    return fields


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
    # Always present when a figure is, because its absence would be read as
    # "exact" by anyone who met the field on one deployment and not another.
    if exc.estimated is not None:
        fields["basis"] = exc.basis
    return fields


def install_error_handlers(
    app: FastAPI,
    *,
    envelope: str = "admin",
    auth_mode: str | None = None,
    surface: str = "admin",
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
        status = _status_for(exc)
        _log(request, exc, status)
        if isinstance(exc, NotAuthorizedError):
            await _audit_refusal(request, exc)
        await _record_refusal(
            request,
            code=exc.code,
            status=status,
            message=exc.public_message,
            # The same figures the body carries, from the same function, which
            # is what makes a stored refusal a copy of the caller's own answer
            # rather than a second opinion about it.
            figures=public_details(exc),
            surface=surface,
        )
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
        # Stored like any other refusal, with no figures, because a caller
        # holding a request id and a 500 has exactly the problem this table was
        # built for: a correct-looking failure with nothing in it to act on.
        # The traceback stays in the log — what is stored here is what the
        # caller was sent, which is a code and an apology.
        await _record_refusal(
            request,
            code=INTERNAL_ERROR_CODE,
            status=500,
            message=INTERNAL_ERROR_MESSAGE,
            figures={},
            surface=surface,
        )
        if envelope == "openai":
            error: dict[str, object] = {
                "type": "api_error",
                "code": INTERNAL_ERROR_CODE,
                "message": INTERNAL_ERROR_MESSAGE,
            }
            if request_id is not None:
                error["request_id"] = request_id
            body: dict[str, object] = {"error": error}
        else:
            body = {"code": INTERNAL_ERROR_CODE, "message": INTERNAL_ERROR_MESSAGE}
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
