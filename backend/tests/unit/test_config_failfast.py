"""Startup assertions that must never be downgraded to warnings.

Both cases here are silent total compromises if they reach production, and
neither is visible from the outside: an open admin API looks identical to a
working one until someone notices, and a placeholder pepper still verifies
keys correctly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings

REAL_SECRETS = {
    "api_key_pepper": "real-pepper",
    "totp_encryption_key": "real-totp-key",
    "session_signing_key": "real-session-key",
    "proxy_shared_secret": "real-proxy-secret",
}


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
