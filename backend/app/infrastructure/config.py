"""Application settings.

Non-secret configuration comes from environment variables; secrets are
mounted as files and read through `secrets_dir`, because environment
variables show up in `docker inspect` output and in the process list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["tailnet", "local", "dev"]
Environment = Literal["development", "production"]
CacheBackend = Literal["redis", "memory"]

SECRETS_DIR = Path("/run/secrets")
_secrets_dir = str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None
"""Docker mounts secrets here; a developer machine has no such directory and
pydantic-settings warns on every instantiation if pointed at a missing path."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir=_secrets_dir,
        extra="ignore",
        populate_by_name=True,
    )

    env: Environment = "development"
    auth_mode: AuthMode = "dev"
    expose_openapi_flag: bool = Field(default=False, alias="EXPOSE_OPENAPI")

    tailnet_ip: str = "127.0.0.1"
    proxy_hostname: str = "api.nexus.rcsl.online"

    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    cache_backend: CacheBackend = "redis"
    """`memory` is per-process and therefore wrong for anything counted across
    workers. Chosen explicitly, never inferred, so it cannot be reached in a
    deployment by accident."""

    ollama_base_url: str = "http://host.docker.internal:11434"

    session_absolute_ttl_seconds: int = 12 * 3600
    session_idle_ttl_seconds: int = 3600
    invitation_ttl_seconds: int = 72 * 3600

    allowed_countries: str = "TW,AU"
    geoip_db_path: str = "/data/GeoLite2-Country.mmdb"

    bootstrap_admin_login: str = ""

    max_concurrent_inference: int = 2
    max_tokens_ceiling: int = 4096
    max_context_length: int = 32768
    request_timeout_seconds: int = 300

    api_key_pepper: str = Field(default="dev-pepper-not-for-production")
    api_key_pepper_previous: str = Field(
        default="",
        description="Set during a pepper rotation so keys signed with the old "
        "value keep verifying until they are reissued.",
    )
    totp_encryption_key: str = Field(default="dev-totp-key-not-for-production")
    session_signing_key: str = Field(default="dev-session-key-not-for-production")
    proxy_shared_secret: str = Field(default="dev-proxy-secret-not-for-production")

    @property
    def allowed_country_set(self) -> frozenset[str]:
        return frozenset(c.strip().upper() for c in self.allowed_countries.split(",") if c.strip())

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def expose_openapi(self) -> bool:
        """Schema and Swagger UI on the gateway.

        Gated on an explicit opt-in rather than on `not is_production`. The
        default `ENV` is `development`, and `.env.example` ships it, so a
        deployment that filled in the secrets and left the top of the file
        alone was serving its full internal schema publicly. Requiring a
        deliberate `EXPOSE_OPENAPI=true` means forgetting fails closed.
        """
        return self.expose_openapi_flag and not self.is_production

    @model_validator(mode="after")
    def _refuse_dev_auth_in_production(self) -> Settings:
        """Fail fast rather than silently serving an unauthenticated admin API.

        `AUTH_MODE=dev` injects a fixed admin actor and disables the geo and
        trusted-proxy checks, which is the only way the stack runs on a
        developer machine. A deployment that reaches production with it still
        set must refuse to boot; a warning would be missed.
        """
        if self.env == "production" and self.auth_mode == "dev":
            raise ValueError(
                "AUTH_MODE=dev cannot be used with ENV=production: it bypasses "
                "authentication entirely. Set AUTH_MODE to 'tailnet' or 'local'."
            )
        return self

    @model_validator(mode="after")
    def _refuse_placeholder_secrets_in_production(self) -> Settings:
        """The default secrets are development placeholders and are committed
        to the repository in .env.example. Reaching production with one still
        in place would be a silent, total compromise of that mechanism."""
        if not self.is_production:
            return self

        placeholders = {
            "api_key_pepper": self.api_key_pepper,
            "totp_encryption_key": self.totp_encryption_key,
            "session_signing_key": self.session_signing_key,
            "proxy_shared_secret": self.proxy_shared_secret,
            # Included because the placeholder is embedded in a URL rather than
            # standing alone, which is exactly why it was missed before.
            "database_url": self.database_url,
        }
        offenders = [name for name, value in placeholders.items() if "not-for-production" in value]
        if offenders:
            raise ValueError(
                f"Placeholder secrets present in production: {', '.join(sorted(offenders))}. "
                "Mount real values under /run/secrets."
            )
        return self

    @model_validator(mode="after")
    def _refuse_in_memory_cache_in_production(self) -> Settings:
        """An in-memory cache silently makes rate limits per-worker, so a
        deployment would appear to enforce a limit it does not."""
        if self.is_production and self.cache_backend == "memory":
            raise ValueError(
                "CACHE_BACKEND=memory cannot be used with ENV=production: rate "
                "limits would be counted per process rather than per key."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
