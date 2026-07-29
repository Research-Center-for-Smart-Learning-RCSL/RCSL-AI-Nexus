"""Startup assertions that must never be downgraded to warnings.

Both cases here are silent total compromises if they reach production, and
neither is visible from the outside: an open admin API looks identical to a
working one until someone notices, and a placeholder pepper still verifies
keys correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings

REAL_SECRETS = {
    "api_key_pepper": "real-pepper",
    "totp_encryption_key": "real-totp-key",
    "session_signing_key": "real-session-key",
    "proxy_shared_secret": "real-proxy-secret",
    "metrics_scrape_token": "real-metrics-token",
    "qdrant_api_key": "real-qdrant-key",
    "database_url": "postgresql+asyncpg://nexus:real@db:5432/nexus",
    "cache_backend": "redis",
}

# Settings reads ambient environment, so without this a developer's shell
# decides whether these pass. That is how CACHE_BACKEND=memory exported for an
# integration run made the production cases fail.
_AMBIENT = (
    "ENV",
    "AUTH_MODE",
    "CACHE_BACKEND",
    "DATABASE_URL",
    "REDIS_URL",
    "API_KEY_PEPPER",
    "TOTP_ENCRYPTION_KEY",
    "SESSION_SIGNING_KEY",
    "PROXY_SHARED_SECRET",
    "METRICS_SCRAPE_TOKEN",
    "METRICS_ENABLED",
    "QDRANT_API_KEY",
    "ALLOWED_COUNTRIES",
    "EXPOSE_OPENAPI",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)
    # The repository's own .env would be read otherwise, for the same reason.
    monkeypatch.chdir(Path(__file__).resolve().parents[1])


def test_dev_auth_mode_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        Settings(env="production", auth_mode="dev", **REAL_SECRETS)


def test_dev_auth_mode_is_fine_in_development() -> None:
    settings = Settings(env="development", auth_mode="dev")
    assert settings.auth_mode == "dev"


@pytest.mark.parametrize("mode", ["tailnet", "local"])
def test_real_auth_modes_are_accepted_in_production(mode: str) -> None:
    settings = Settings(env="production", auth_mode=mode, **REAL_SECRETS)
    assert settings.is_production is True


def test_placeholder_secrets_are_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Placeholder secrets"):
        Settings(env="production", auth_mode="tailnet")


def test_placeholder_secrets_are_fine_in_development() -> None:
    settings = Settings(env="development", auth_mode="dev")
    assert "not-for-production" in settings.api_key_pepper


def test_allowed_countries_parsing() -> None:
    settings = Settings(allowed_countries=" tw , au ")
    assert settings.allowed_country_set == frozenset({"TW", "AU"})


def test_in_memory_cache_is_rejected_in_production() -> None:
    """Per-process counting would look like a rate limit without being one."""
    with pytest.raises(ValidationError, match="CACHE_BACKEND=memory"):
        Settings(
            **{
                **REAL_SECRETS,
                "env": "production",
                "auth_mode": "tailnet",
                "cache_backend": "memory",
            }
        )


def test_placeholder_metrics_token_is_rejected_only_when_metrics_are_enabled() -> None:
    """The scrape token guards /metrics, so a placeholder is a production defect
    when metrics are exposed. A deployment that runs no Prometheus turns them off
    and is not forced to invent a token it will not use."""
    base = {**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"}
    placeholder = "dev-metrics-token-not-for-production"

    with pytest.raises(ValidationError, match="metrics_scrape_token"):
        Settings(**{**base, "metrics_scrape_token": placeholder})

    disabled = Settings(**{**base, "metrics_scrape_token": placeholder, "metrics_enabled": False})
    assert disabled.metrics_enabled is False


def test_the_qdrant_key_is_required_unconditionally() -> None:
    """Unlike the metrics token, there is no flag that makes this optional.

    Qdrant ships with no authentication at all, so a placeholder key leaves the
    whole knowledge base readable to anything that reaches the admin network.
    There is no deployment shape in which that is the intended state, so there
    is nothing to make it conditional on.
    """
    base = {**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"}
    with pytest.raises(ValidationError, match="qdrant_api_key"):
        Settings(**{**base, "qdrant_api_key": "dev-qdrant-key-not-for-production"})


def test_a_placeholder_hidden_inside_a_url_is_caught() -> None:
    """The database password sits inside a connection string rather than
    standing alone, which is why it escaped the original check."""
    with pytest.raises(ValidationError, match="database_url"):
        Settings(
            **{
                **REAL_SECRETS,
                "env": "production",
                "auth_mode": "tailnet",
                "database_url": "postgresql+asyncpg://nexus:dev-postgres-not-for-production@db/nexus",
            }
        )


def test_the_schema_is_not_exposed_unless_explicitly_asked_for() -> None:
    """Gating on `not is_production` meant a deployment that filled in the
    secrets and left ENV at its default served its full internal schema."""
    assert Settings().expose_openapi is False
    assert Settings(expose_openapi_flag=True).expose_openapi is True
    assert (
        Settings(
            **{**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"},
            expose_openapi_flag=True,
        ).expose_openapi
        is False
    ), "production wins over the flag"


def test_the_proxy_timeout_stays_above_the_generation_deadline() -> None:
    """Two files in two languages hold one ordering, and only a comment says so.

    The frontend proxies /admin/* with `NextResponse.rewrite`, and Next applies
    a socket timeout to a proxied request. Whichever of the two limits fires
    first decides what the caller sees: the backend's deadline ends the stream
    with `finish_reason=length`, while the proxy's resets the socket and leaves
    nothing in any log — which is exactly how a 93-second generation once
    surfaced in the browser as a 500 (PROGRESS, 2026-07-27).

    So the proxy's value must stay above the backend's, and raising the
    deadline without raising it would move that silent cut rather than remove
    it. Asserted here because a comment in each file cannot enforce an
    invariant that spans both.
    """
    root = Path(__file__).resolve().parents[3]

    # `encoding` is not optional here. `read_text()` without it decodes using
    # the process locale, which on a Windows development machine set to
    # Traditional Chinese is cp950, and both files carry UTF-8 punctuation in
    # their comments. The test then died on a `UnicodeDecodeError` rather than
    # on the invariant it exists to check, and only on machines whose locale
    # happened not to be UTF-8.
    config = (root / "frontend" / "next.config.js").read_text(encoding="utf-8")
    match = re.search(r"proxyTimeout:\s*([\d_]+)", config)
    assert match is not None, "proxyTimeout is gone; the 30s default is back"
    proxy_seconds = int(match.group(1).replace("_", "")) / 1000

    env = (root / ".env.example").read_text(encoding="utf-8")
    deadline_match = re.search(r"^GENERATION_DEADLINE_SECONDS=(\d+)", env, re.MULTILINE)
    assert deadline_match is not None, "the deadline must stay discoverable in .env.example"
    deadline = int(deadline_match.group(1))

    assert proxy_seconds > deadline, (
        f"proxyTimeout ({proxy_seconds}s) must exceed the generation deadline "
        f"({deadline}s), or a cut arrives with no reason attached"
    )
    assert deadline >= Settings().generation_deadline_seconds, (
        "the documented value must not be below the code default"
    )
