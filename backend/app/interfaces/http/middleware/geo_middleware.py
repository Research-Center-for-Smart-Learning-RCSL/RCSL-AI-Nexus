"""The country allowlist as middleware, for the public admin entrance.

The gateway applies the same filter inline, inside API key authentication,
because it already resolves the client address there. The admin entrance has
no such chokepoint: its routes are reached by sessions, by invitation tokens,
and by nothing at all, so the check has to sit in front of all of them.

**This was missing, and four places claimed it existed** — security.md §4.1(a)
("This filter applies to the public admin entrance as well as the gateway.
The control plane's worst-case damage is strictly greater... so there is no
argument for restricting it less"), §13.0's implemented table, the §14
pre-launch checklist, and a comment in the invitations router. A claimed
control that does not exist is worse than an absent one, because it stops
people looking.

Health is exempt. The reverse proxy and Compose have to be able to probe the
service, and neither is in an allowed country in any meaningful sense.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.domain.exceptions import DomainError
from app.interfaces.http.errors import error_response
from app.interfaces.http.middleware.client_ip import resolve_client_ip

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})


class GeoFilterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, auth_mode: str) -> None:
        super().__init__(app)
        self._auth_mode = auth_mode

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        try:
            # Resolving the address is itself a check: outside development it
            # requires the proxy's shared secret and an X-Forwarded-For, so a
            # request that did not come through openresty is refused here.
            # That check previously ran on the three login routes only.
            request.app.state.geo_filter.assert_allowed(resolve_client_ip(request))
        except DomainError as exc:
            logger.info(
                "perimeter_rejected path=%s code=%s detail=%s",
                request.url.path,
                exc.code,
                exc.detail,
            )
            # Returned rather than raised: an exception here escapes past
            # ExceptionMiddleware and surfaces as a 500. See errors.py.
            return error_response(exc, envelope="admin", auth_mode=self._auth_mode)

        return await call_next(request)
