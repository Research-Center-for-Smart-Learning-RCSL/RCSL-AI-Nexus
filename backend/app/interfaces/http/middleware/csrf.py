"""Double-submit CSRF protection for the public entrance.

The public entrance authenticates with a cookie, which the browser attaches to
any request the page can be made to issue, so a state-changing request needs
proof that the page issuing it could read this origin.

`SameSite=Lax` alone is not that proof. It still permits top-level POST
navigations, which is exactly the shape of a hostile form submission. So a
random value is placed in a companion cookie that is deliberately **not**
`HttpOnly`, and must be echoed in a request header. A cross-origin page can
cause the cookie to be sent but cannot read it, so it cannot produce the
header. See docs/architecture/security.md section 5.3.

This middleware is only half the check, and it is the half that works before
anyone is signed in: the login and invitation endpoints are unauthenticated
and still need protection. Once a session exists, `identity.py` additionally
compares the header against the token held server-side, which is what defeats
an attacker who can write cookies for this domain but not read them.

**The tailnet entrance does not install this.** It has no ambient credential:
identity comes from a header injected by `tailscale serve` on each request,
and a hostile page cannot cause that header to be added.
"""

from __future__ import annotations

import logging
import secrets
from hmac import compare_digest

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.domain.exceptions import CsrfValidationError
from app.interfaces.http.errors import error_response
from app.interfaces.http.middleware.identity import SAFE_METHODS

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32


def _tokens_match(presented: str, expected: str) -> bool:
    """Constant-time comparison that tolerates a non-ASCII header.

    Starlette decodes header values as latin-1, so a header carrying bytes
    above 0x7f yields a `str` that `hmac.compare_digest` refuses with a
    `TypeError` — which, uncaught, becomes a 500 and defeats the deliberate
    403. Comparing the utf-8 encodings sidesteps that; a token is url-safe
    base64, so a legitimate one is pure ASCII and unaffected.
    """
    return compare_digest(presented.encode("utf-8", "ignore"), expected.encode("utf-8", "ignore"))


class CsrfMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        cookie_name: str,
        header_name: str,
        secure: bool,
        max_age_seconds: int,
    ) -> None:
        super().__init__(app)
        self._cookie = cookie_name
        self._header = header_name
        self._secure = secure
        self._max_age = max_age_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # An empty-string cookie is treated as absent, not present. A cookie
        # set to "" failed the double-submit check *and*, when the guard was
        # `is None`, was never re-issued, so every non-safe request stayed
        # wedged at 403 until the client deleted the cookie itself.
        presented_cookie = request.cookies.get(self._cookie) or None

        if request.method not in SAFE_METHODS:
            failure = self._double_submit_failure(request, presented_cookie)
            if failure is not None:
                logger.warning(
                    "csrf_rejected path=%s method=%s detail=%s",
                    request.url.path,
                    request.method,
                    failure.detail,
                )
                # Returned, not raised: an exception here would escape past
                # ExceptionMiddleware and surface as a 500. See
                # interfaces/http/errors.py:error_response.
                response: Response = error_response(failure, envelope="admin")
                # Re-seed on the rejection too, so a wedged or missing cookie
                # is replaced by the same response that reports the failure and
                # the client's retry can succeed.
                if presented_cookie is None:
                    self._issue(response, secrets.token_urlsafe(TOKEN_BYTES))
                return response

        response = await call_next(request)

        if presented_cookie is None:
            # Issued on the first response of a visit, which is the `GET /me`
            # the session provider makes before anything else. Without this the
            # login POST would have no cookie to echo and could never succeed.
            self._issue(response, secrets.token_urlsafe(TOKEN_BYTES))

        return response

    def _double_submit_failure(
        self, request: Request, cookie_value: str | None
    ) -> CsrfValidationError | None:
        if not cookie_value:
            return CsrfValidationError(detail=f"no {self._cookie} cookie on {request.method}")

        presented = request.headers.get(self._header, "")
        if not _tokens_match(presented, cookie_value):
            return CsrfValidationError(detail=f"{self._header} does not match the cookie")
        return None

    def _issue(self, response: Response, value: str) -> None:
        response.set_cookie(
            self._cookie,
            value,
            max_age=self._max_age,
            path="/",
            secure=self._secure,
            # Deliberately readable by scripts: the client has to send it back
            # in a header, which is the entire mechanism. It is not a
            # credential, and holding it grants nothing without the session
            # cookie that is HttpOnly.
            httponly=False,
            samesite="lax",
        )


def issue_csrf_cookie(
    response: Response, value: str, *, cookie_name: str, secure: bool, max_age: int
) -> None:
    """Used at login to replace the pre-session value with the session's own.

    From then on the two halves of the double submit are the same value the
    server holds, so `identity.py` can compare against something the client was
    never in a position to choose.
    """
    response.set_cookie(
        cookie_name,
        value,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


__all__ = ["CsrfMiddleware", "issue_csrf_cookie"]
