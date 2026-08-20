"""Startup assertions that must never be downgraded to warnings.

Both cases here are silent total compromises if they reach production, and
neither is visible from the outside: an open admin API looks identical to a
working one until someone notices, and a placeholder pepper still verifies
keys correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
