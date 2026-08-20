from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings
from tests.unit.config_failfast_fixtures import (
    REAL_SECRETS,
)

pytest_plugins = ("tests.unit.config_failfast_fixtures",)


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
