"""A ceiling on the request body, enforced before the body is read.

**Why this exists.** Authentication on every entrance is a FastAPI dependency,
not middleware: `chat.py` reaches it through `ActorDep`, and the admin routers
through their session dependencies. FastAPI resolves the body *before* it
resolves dependencies — `fastapi/routing.py::get_request_handler` calls
`await request.body()` and `await request.json()`, and only then
`solve_dependencies` — so on every one of these apps an unauthenticated caller
already had the whole body buffered in memory and handed to `json.loads` before
anything asked who they were.

Measured against the live deployment on 2026-08-07: a 200 MiB body of NUL bytes
sent to `https://llmapi.rcsl.online/v1/chat/completions` with no credential was
uploaded in full and answered with a 422 JSON decode error. The same endpoint
answers 401 to a *small* well-formed body, which is what made the ordering
visible from outside — the difference is not the size but whether the body
parses, because a parse failure is raised before the dependency that would have
refused the caller.

This is the shape of defect this repository keeps finding: the control existed,
was tested, and sat one step behind the thing it was meant to guard.

**Why it is not left to the proxy.** `client_max_body_size` on the inference
host was found unset — 200 MiB passed it — while the design says `10m`. It is
now also asked for, but the platform already refuses to take the perimeter's
word for the client address (`client_ip.py`) or for tailnet identity
(`StripTailscaleHeadersMiddleware`), and a limit that only exists in someone
else's nginx is a control this deployment cannot verify or restore. The two are
not redundant: nginx keeps the bytes off the machine, this keeps them out of
the process.

**Pure ASGI rather than `BaseHTTPMiddleware`**, for the reason `metrics.py`
gives: the gateway streams, and this middleware has to wrap `receive` rather
than a response.

Two paths, because there are two ways to be too large:

- A declared `Content-Length` over the ceiling is refused without reading a
  byte. This is the ordinary case and the only one that saves the transfer.
- A body that arrives chunked, or that exceeds a `Content-Length` that lied,
  is counted as it passes and refused mid-stream.

**Neither path raises, and the second one is why.** The obvious design was to
raise a `DomainError` out of `receive` and let the registered handler render
it — `ExceptionMiddleware` does sit inside this one, so it would be caught.
FastAPI gets there first: `get_request_handler` wraps the whole body read in
`except Exception: raise HTTPException(status_code=400, detail="There was an
error parsing the body")`, so a 413 raised from `receive` reaches the caller as
a 400 about parsing. Written that way first, and the tests said so.

So both paths build the response here through `error_response`, which exists
for middleware for the same reason (see its docstring). The streaming path then
answers every further `receive` with `http.disconnect` so the application
unwinds, and drops whatever it sends on the way out — that 400 among it.

Rejecting without draining means the client may still be sending when the
response goes out, and some clients report the reset instead of reading the
413. That is the same trade nginx makes with `client_max_body_size`, and the
alternative — reading to the end of a body already known to be too large — is
the cost this exists to avoid.
"""

from __future__ import annotations

import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.domain.exceptions import RequestTooLargeError
from app.interfaces.http.errors import error_response

logger = logging.getLogger(__name__)


def _declared_length(scope: Scope) -> int | None:
    """The caller's own `Content-Length`, if it sent a usable one.

    Headers arrive as raw bytes and are attacker-controlled: a non-numeric or
    negative value is treated as absent rather than trusted or rejected, which
    leaves the streaming counter below as the thing that decides. Refusing the
    request here would make a malformed header a different failure from a
    missing one, and neither tells us anything about the size.
    """
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                declared = int(value)
            except ValueError:
                return None
            return declared if declared >= 0 else None
    return None


class BodySizeLimitMiddleware:
    """Refuse a request body over `max_bytes`, before any handler sees it.

    `envelope` matches the app's own error shape, since a middleware building
    its own response cannot go through the handler that knows which one this
    entrance uses.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int, envelope: str = "admin") -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive; a zero ceiling refuses every request")
        self.app = app
        self._max_bytes = max_bytes
        self._envelope = envelope

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self._max_bytes:
            logger.info(
                "body_rejected path=%s declared=%s limit=%s",
                scope.get("path", ""),
                declared,
                self._max_bytes,
            )
            # The detail names both numbers and stays operator-facing: it
            # reaches a caller only through an open debug window, like every
            # other DomainError detail.
            exc = RequestTooLargeError(
                detail=f"declared content-length {declared} over the {self._max_bytes} limit"
            )
            response = error_response(exc, envelope=self._envelope)
            await response(scope, receive, send)
            return

        # Per-request state, held here rather than on the instance: one
        # middleware object serves every concurrent request, so an attribute
        # would be a counter shared between all of them.
        received = 0
        rejected = False

        async def counting_receive() -> Message:
            """Guards what a declared length cannot: chunked, or a lying one."""
            nonlocal received, rejected
            if rejected:
                # The application is unwinding. Anything but a disconnect here
                # would have it wait for a body that is never coming.
                return {"type": "http.disconnect"}

            message = await receive()
            if message["type"] != "http.request":
                return message

            received += len(message.get("body", b""))
            if received <= self._max_bytes:
                return message

            rejected = True
            logger.info(
                "body_rejected path=%s streamed=%s limit=%s",
                scope.get("path", ""),
                received,
                self._max_bytes,
            )
            exc = RequestTooLargeError(
                detail=f"body reached {received} bytes, over the {self._max_bytes} limit"
            )
            # Sent on the real `send`, before the application has produced
            # anything: it is still inside its own body read.
            await error_response(exc, envelope=self._envelope)(scope, receive, send)
            return {"type": "http.disconnect"}

        async def guarded_send(message: Message) -> None:
            """Drops the application's own response once ours has gone.

            What it drops is FastAPI's `400 There was an error parsing the
            body`, which is how a `ClientDisconnect` surfaces from a body read.
            Two responses on one request would be a protocol error, and the
            second is the less true of the two.
            """
            if rejected:
                return
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
