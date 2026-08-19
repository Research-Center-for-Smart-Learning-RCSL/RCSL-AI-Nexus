"""HTTP handlers boundary."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    DomainError,
    NotAuthorizedError,
)
from app.interfaces.http.request_context import current_request_id

from .details import (
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_MESSAGE,
    error_response,
    public_details,
)
from .mapping import _status_for
from .persistence import _audit_refusal, _log, _record_refusal

logger = logging.getLogger("app.interfaces.http.errors")


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
