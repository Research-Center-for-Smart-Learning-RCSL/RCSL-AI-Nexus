"""Derived values over the unchanged flat settings contract."""

from __future__ import annotations

from typing import Protocol, cast

HOST_COOKIE_PREFIX = "__Host-"


def _drop_host_prefix_if_insecure(name: str, secure: bool) -> str:
    """Browsers reject a `__Host-` cookie that is not also `Secure`.

    Local development of the public entrance runs over plain HTTP, where
    keeping the prefix would mean the cookie is silently discarded and the
    login appears to succeed and then immediately fail. Dropping it is
    confined to that case: `cookie_secure` cannot be false in production.

    The frontend reads the CSRF cookie by name, so a developer who turns this
    off must set `NEXT_PUBLIC_CSRF_COOKIE` to match. Recorded in .env.example.
    """
    if secure or not name.startswith(HOST_COOKIE_PREFIX):
        return name
    return name[len(HOST_COOKIE_PREFIX) :]


class _DerivedSettings(Protocol):
    allowed_countries: str
    env: str
    session_cookie_name: str
    csrf_cookie_name: str
    cookie_secure: bool
    expose_openapi_flag: bool
    gateway_base_url_override: str
    proxy_hostname: str


class DerivedValuesMixin:
    @property
    def allowed_country_set(self) -> frozenset[str]:
        value = cast(_DerivedSettings, self).allowed_countries
        return frozenset(c.strip().upper() for c in value.split(",") if c.strip())

    @property
    def is_production(self) -> bool:
        return cast(_DerivedSettings, self).env == "production"

    @property
    def effective_session_cookie(self) -> str:
        settings = cast(_DerivedSettings, self)
        return _drop_host_prefix_if_insecure(settings.session_cookie_name, settings.cookie_secure)

    @property
    def effective_csrf_cookie(self) -> str:
        settings = cast(_DerivedSettings, self)
        return _drop_host_prefix_if_insecure(settings.csrf_cookie_name, settings.cookie_secure)

    @property
    def expose_openapi(self) -> bool:
        """Schema and Swagger UI on the gateway.

        Gated on an explicit opt-in rather than on `not is_production`. The
        default `ENV` is `development`, and `.env.example` ships it, so a
        deployment that filled in the secrets and left the top of the file
        alone was serving its full internal schema publicly. Requiring a
        deliberate `EXPOSE_OPENAPI=true` means forgetting fails closed.
        """
        return cast(_DerivedSettings, self).expose_openapi_flag and not self.is_production

    @property
    def gateway_base_url(self) -> str:
        """The origin an integrator points a client library at.

        Derived from `PROXY_HOSTNAME` unless overridden, so the ordinary
        deployment configures the hostname once. No trailing slash: callers
        append `/v1/...`, and the snippets shown in the UI are copied verbatim.

        A bare hostname in the override is completed rather than passed
        through. `GATEWAY_BASE_URL=api.example.com` yields `api.example.com/v1`,
        which no client library can use, and the failure appears in somebody
        else's terminal long after the setting was written.
        """
        settings = cast(_DerivedSettings, self)
        origin = settings.gateway_base_url_override.strip() or f"https://{settings.proxy_hostname}"
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        return origin.rstrip("/")
