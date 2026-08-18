"""`Cache-Control: no-store` on every response that does not already choose one.

**Why this exists.** Two places in this codebase set the header — `sse.py` sets
`no-cache` on a stream and `qr.py` sets `no-store, private` on an enrolment QR —
and both were written by somebody thinking about that one response. Everything
else says nothing at all: the admin API returns users, keys, audit rows,
transcripts and refusals with no instruction about storage, and so does the
gateway, whose responses carry the caller's prompt and the model's completion.

An HTTP cache that is told nothing is not forbidden from storing a response. A
`200` to a `GET` with no `Cache-Control` and no validators is heuristically
cacheable, and the deployment has a cache-capable intermediary in the path that
this project does not administer: the NTNU openresty proxy in front of the
public entrance (security.md §15.1 and §15.2). "It is probably not configured to
cache" is the same shape of argument as "nginx probably limits the body size",
which `body_limit.py` records being wrong about, on this deployment, by 200 MiB.

Found on 2026-08-18 while investigating something else, and it was **not** the
cause of that: an intermittently stale read in the browser was checked against
this and excluded (PROGRESS 2026-08-18). It is recorded and fixed here on its
own merits rather than folded into that story.

**It never overwrites a header the response already set.** The two callers above
chose their values deliberately, and a stream in particular is a response where
`no-cache` and `no-store` are not interchangeable in how intermediaries treat
buffering. Widening those two to `no-store` may be right and is a separate
decision with its own risk; this middleware is only about the responses that
currently say nothing.

**One response does not get it, and it is worth naming.** An exception that
escapes to Starlette's `ServerErrorMiddleware` is answered outside every user
middleware, including this one. In practice that is a narrow set: all three
applications install their own handlers (`install_error_handlers`), so an
anticipated 500 is built inside the stack and does carry the header. What is
uncovered is the response to a failure nothing anticipated, whose body is a
fixed string.

`no-store` rather than `no-store, private`: `private` bounds *which* cache may
store a response, and `no-store` already forbids all of them, so the pair adds
nothing here beyond what `qr.py` chose for belt and braces.

**Pure ASGI rather than `BaseHTTPMiddleware`**, for the reason `metrics.py` and
`request_context.py` both give: the gateway streams, and `BaseHTTPMiddleware`
runs the downstream app in a separate task. This only has to touch one message.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = b"cache-control"
VALUE = b"no-store"


class CacheControlMiddleware:
    """Adds the header to `http.response.start` unless one is already there."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                # Case-insensitively, because a response is free to spell it
                # however it likes and a second `Cache-Control` line would leave
                # the intermediary to pick.
                if not any(name.lower() == HEADER for name, _ in headers):
                    headers.append((HEADER, VALUE))
            await send(message)

        await self.app(scope, receive, send_with_header)


__all__ = ["CacheControlMiddleware"]
