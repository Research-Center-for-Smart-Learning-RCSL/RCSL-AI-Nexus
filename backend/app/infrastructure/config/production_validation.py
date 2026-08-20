"""Production Validation for settings."""

from __future__ import annotations

from typing import Protocol, Self, cast

from pydantic import model_validator
from pydantic_settings import BaseSettings


class _ProductionSettings(Protocol):
    env: str
    auth_mode: str
    is_production: bool
    cookie_secure: bool
    cache_backend: str


class ProductionValidationMixin(BaseSettings):
    @model_validator(mode="after")
    def _refuse_dev_auth_in_production(self) -> Self:
        """Fail fast rather than silently serving an unauthenticated admin API.

        `AUTH_MODE=dev` injects a fixed admin actor and disables the geo and
        trusted-proxy checks, which is the only way the stack runs on a
        developer machine. A deployment that reaches production with it still
        set must refuse to boot; a warning would be missed.
        """
        settings = cast(_ProductionSettings, self)
        if settings.env == "production" and settings.auth_mode == "dev":
            raise ValueError(
                "AUTH_MODE=dev cannot be used with ENV=production: it bypasses "
                "authentication entirely. Set AUTH_MODE to 'tailnet' or 'local'."
            )
        return self

    @model_validator(mode="after")
    def _refuse_insecure_cookies_in_production(self) -> Self:
        """Without `Secure`, the session cookie is sent over plain HTTP and the
        `__Host-` prefix is dropped, which removes both the transport guarantee
        and the same-origin binding that prefix provides. The setting exists
        only so the public entrance can be exercised locally."""
        settings = cast(_ProductionSettings, self)
        if settings.is_production and not settings.cookie_secure:
            raise ValueError(
                "COOKIE_SECURE=false cannot be used with ENV=production: the "
                "session cookie would travel in clear text."
            )
        return self

    @model_validator(mode="after")
    def _refuse_in_memory_cache_in_production(self) -> Self:
        """An in-memory cache silently makes rate limits per-worker, so a
        deployment would appear to enforce a limit it does not."""
        settings = cast(_ProductionSettings, self)
        if settings.is_production and settings.cache_backend == "memory":
            raise ValueError(
                "CACHE_BACKEND=memory cannot be used with ENV=production: rate "
                "limits would be counted per process rather than per key."
            )
        return self
