"""Secret Validation for settings."""

from __future__ import annotations

from typing import Protocol, Self, cast

from pydantic import model_validator
from pydantic_settings import BaseSettings


class _SecretSettings(Protocol):
    is_production: bool
    api_key_pepper: str
    totp_encryption_key: str
    session_signing_key: str
    proxy_shared_secret: str
    database_url: str
    qdrant_api_key: str
    metrics_enabled: bool
    metrics_scrape_token: str


class SecretValidationMixin(BaseSettings):
    @model_validator(mode="after")
    def _refuse_placeholder_secrets_in_production(self) -> Self:
        """The default secrets are development placeholders and are committed
        to the repository in .env.example. Reaching production with one still
        in place would be a silent, total compromise of that mechanism."""
        settings = cast(_SecretSettings, self)
        if not settings.is_production:
            return self

        placeholders = {
            "api_key_pepper": settings.api_key_pepper,
            "totp_encryption_key": settings.totp_encryption_key,
            "session_signing_key": settings.session_signing_key,
            "proxy_shared_secret": settings.proxy_shared_secret,
            # Included because the placeholder is embedded in a URL rather than
            # standing alone, which is exactly why it was missed before.
            "database_url": settings.database_url,
            # Unconditional, unlike the metrics token below: an unauthenticated
            # Qdrant on the admin network is a full read of the knowledge base
            # for anything that gets onto it, and there is no deployment shape
            # in which the placeholder is acceptable.
            "qdrant_api_key": settings.qdrant_api_key,
        }
        # Only when metrics are actually exposed: a deployment that runs no
        # Prometheus has no token to protect and should not be forced to invent one.
        if settings.metrics_enabled:
            placeholders["metrics_scrape_token"] = settings.metrics_scrape_token
        offenders = [name for name, value in placeholders.items() if "not-for-production" in value]
        if offenders:
            raise ValueError(
                f"Placeholder secrets present in production: {', '.join(sorted(offenders))}. "
                "Mount real values under /run/secrets."
            )
        return self
