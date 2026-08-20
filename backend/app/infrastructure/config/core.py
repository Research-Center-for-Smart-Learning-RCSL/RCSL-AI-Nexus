"""Flat core setting declarations."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["tailnet", "local", "dev"]
Environment = Literal["development", "production"]
CacheBackend = Literal["redis", "memory"]

SECRETS_DIR = Path("/run/secrets")
_secrets_dir = str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None


# Named rather than written inline, because the composed `Settings` has to
# restate it: see the note on that class. A second literal would drift.
SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    secrets_dir=_secrets_dir,
    extra="ignore",
    populate_by_name=True,
)


class CoreSettings(BaseSettings):
    model_config = SETTINGS_CONFIG

    env: Environment = "development"

    auth_mode: AuthMode = "dev"

    expose_openapi_flag: bool = Field(default=False, alias="EXPOSE_OPENAPI")

    log_level: str = Field(
        default="INFO",
        description=(
            "Level for the application's own `app.*` loggers, not the root. "
            "INFO by default because the lines below WARNING are the ones that "
            "say *why* a request was refused — `perimeter_rejected` is the only "
            "place the three causes of `untrusted_proxy` are distinguished. "
            "Nothing configured logging at all before 2026-08-03, which meant "
            "Python's WARNING-level fallback handler discarded every one of "
            "them (infrastructure/logging_config.py)."
        ),
    )

    tailnet_ip: str = "127.0.0.1"

    proxy_hostname: str = "llmapi.rcsl.online"

    admin_base_url: str = "http://localhost:3000"
    """Origin of the management UI, used to build invitation and reset links.

    Configured rather than derived from the request, because the link is issued
    on whichever entrance the administrator is using and must always point at
    the public one: a tailnet URL handed to someone who has no Tailscale is a
    link they cannot open.
    """

    gateway_base_url_override: str = Field(default="", alias="GATEWAY_BASE_URL")
    """Where callers reach the inference API, shown in the management UI beside
    a newly issued key.

    Set only when the public origin is not `https://` plus `PROXY_HOSTNAME` —
    a different port in development, say. Empty means "derive it", so the two
    cannot drift apart in the ordinary deployment where they agree.

    It is configuration rather than something read off the request because the
    UI asking is on the *admin* origin: the request that renders the snippet
    arrives at a different host from the one the snippet must name.
    """

    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"

    db_pool_size: int = 20

    db_max_overflow: int = 10
    """A request holds a connection for its whole duration, and an audited one
    needs a second, so the pool must exceed the concurrent request count rather
    than sit near it. 30 across three services stays under Postgres's default
    100 max_connections. See infrastructure/db.py."""

    redis_url: str = "redis://localhost:6379/0"

    redis_password: str = ""

    cache_backend: CacheBackend = "redis"
    """`memory` is per-process and therefore wrong for anything counted across
    workers. Chosen explicitly, never inferred, so it cannot be reached in a
    deployment by accident."""
