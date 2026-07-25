"""HTTP request metrics, as a pure ASGI middleware.

Pure ASGI rather than `BaseHTTPMiddleware` on purpose: the gateway's whole
reason for being is streaming, and `BaseHTTPMiddleware` returns from `dispatch`
once the response object exists, which for a `StreamingResponse` is before a
single token has been sent. Timing and the in-progress gauge would then measure
time-to-first-byte, not the duration the request actually occupied the process.
Wrapping `send` instead lets both be recorded when the response truly finishes.

The route label is the matched template (`/admin/api-keys/{key_id}`), never the
raw path, so an id in the URL does not become a distinct time series. Anything
that matched no route collapses to a single `__unmatched__` label, which is what
keeps a port scanner from turning 404s into unbounded cardinality.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The method is a label, and the HTTP method is a free token: a client may send
# any word. Without an allowlist that is the same unbounded cardinality the route
# label guards against, so an unrecognised method collapses to one bucket.
_KNOWN_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)


def _method_label(method: str) -> str:
    return method if method in _KNOWN_METHODS else "OTHER"


def _route_label(scope: Scope) -> str:
    # `endpoint` is written into the scope by the router only on a full match
    # (starlette.routing, `scope.update(child_scope)`); its absence means nothing
    # matched, and the raw path of a 404 is attacker-controlled.
    if "endpoint" not in scope:
        return "__unmatched__"
    path: str = scope.get("path", "") or "/"
    params = scope.get("path_params") or {}
    if not params:
        return path
    # Rebuild the template by replacing whole path segments, not substrings: a
    # naive `path.replace(value, ...)` rewrites the wrong place when the value
    # also occurs earlier (id "1" hitting the "1" in "/api/v1/...") or equals a
    # static segment. Params sit on segment boundaries and typically trail, so
    # the rightmost segment equal to the value is the one to templatise.
    segments = path.split("/")
    for name, value in params.items():
        text = str(value)
        if not text:
            continue
        for i in range(len(segments) - 1, -1, -1):
            if segments[i] == text:
                segments[i] = "{" + name + "}"
                break
    return "/".join(segments)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Read from the app at request time rather than construction time: the
        # registry is built in the lifespan, after create_app has added this
        # middleware. An app built without a lifespan (a few tests) has no
        # metrics, and instrumentation must never be the thing that breaks it.
        metrics = getattr(scope["app"].state, "metrics", None)
        if metrics is None:
            await self.app(scope, receive, send)
            return

        method = _method_label(scope["method"])
        status = 500
        """Defaults to 500 so an exception that propagates past this middleware,
        aborting before any `http.response.start`, is still recorded as the error
        it is rather than dropped."""

        start = time.perf_counter()
        metrics.http_in_progress.inc()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.http_in_progress.dec()
            metrics.observe_http(method, _route_label(scope), status, time.perf_counter() - start)
