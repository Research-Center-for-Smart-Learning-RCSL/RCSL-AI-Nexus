"""HTTP details boundary."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    ApiKeyLifetimeError,
    CapabilityNotIssuedError,
    ContextTooLongError,
    DomainError,
    InsufficientMemoryError,
    QuotaExceededError,
    RateLimitedError,
    ServerOverloadedError,
    UploadRejectedError,
    WeakPasswordError,
)
from app.interfaces.http.request_context import current_request_id, debug_detail_active

from .mapping import _openai_type_for, _status_for

INTERNAL_ERROR_CODE = "internal_error"


INTERNAL_ERROR_MESSAGE = "An internal error occurred."


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
