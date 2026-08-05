"""The request id, and the per-request debug window, as ambient context.

Contextvars rather than `request.state`, because the two places that need
these most cannot reach the request: the SSE frame generator (handed to
`StreamingResponse` and driven after the handler frame is gone) and the 500
handler (running in `ServerErrorMiddleware`, outside every app middleware).
A contextvar set at the top of the request survives into both, since each
request runs as one asyncio task and both run inside it.

The id is the bridge between a caller's failure and the log line that explains
it. `DomainError.detail` is deliberately never in a response body
(security.md section 5), so precision for the caller has to come from
correlation instead: they quote `request_id`, the operator greps for it, and
the detail was there all along. The docstring on `DomainError` promised this
mechanism from the start; until 2026-08-05 nothing implemented it.

`debug_detail_until` is the one exception to "detail never leaves", and it is
time-boxed and per-credential: an administrator sets `debug_logging_until` on
an API key (or a user), and while the window is open, error envelopes for that
caller carry `error.detail`. The window is granted from the management UI,
audited, and expires on its own — the field existed in the schema since the
first migration and was consumed by nothing until 2026-08-05.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"

_request_id: ContextVar[str | None] = ContextVar("nexus_request_id", default=None)
_debug_detail_until: ContextVar[datetime | None] = ContextVar(
    "nexus_debug_detail_until", default=None
)


def current_request_id() -> str | None:
    return _request_id.get()


def grant_debug_detail(until: datetime | None) -> None:
    """Called by the identity resolvers once the credential is known.

    Rejections that happen before a credential is resolved (missing token,
    malformed token) can never carry detail, which is correct: the window
    belongs to a credential, not to whoever failed to present one.
    """
    _debug_detail_until.set(until)


def debug_detail_active() -> bool:
    until = _debug_detail_until.get()
    return until is not None and datetime.now(UTC) < until


class RequestContextMiddleware:
    """Mints the id, sets the contextvar, echoes the header.

    Pure ASGI rather than `BaseHTTPMiddleware`: the latter runs the downstream
    app in a separate task, and the contextvar would be set in a context the
    handler never sees.

    The vars are set fresh at the start of every request and deliberately not
    reset on the way out. Resetting in a `finally` would clear them *while an
    exception is still propagating* to `ServerErrorMiddleware`, which sits
    outside this middleware and is exactly where the 500 handler needs to read
    the id. A stale value after the response is sent is unreadable in
    practice — the next request on the task overwrites it before any code
    reads it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = f"req_{uuid.uuid4().hex[:16]}"
        _request_id.set(request_id)
        _debug_detail_until.set(None)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_with_header)
