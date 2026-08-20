"""Configuring the platform through the admin API, end to end.

This is Phase 1's stated goal exercised as one sequence: register a model,
bind a routing policy to it, issue an API key, and see the dashboard reflect
all three. Every step goes over HTTP against a real Postgres, because the
things that break here are wiring rather than logic — a response shape the
frontend cannot parse, a foreign key nobody flushed, a scope checked against
the wrong actor.

Runs on the tailnet entrance. It has no CSRF to satisfy and no login to
perform, which keeps the test about the management API rather than about the
credential flow that `test_auth_end_to_end.py` already covers.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import get_settings
from tests.integration.conftest import TEST_DATABASE_URL, reset_schema

BOOTSTRAP_LOGIN = "dev@localhost"

NODE_ID = "local"


@pytest.fixture
def admin() -> Iterator[TestClient]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    reset_schema(TEST_DATABASE_URL)

    previous = dict(os.environ)
    os.environ.update(
        {
            "DATABASE_URL": TEST_DATABASE_URL,
            "AUTH_MODE": "dev",
            "CACHE_BACKEND": "memory",
            "BOOTSTRAP_ADMIN_LOGIN": BOOTSTRAP_LOGIN,
            "COOKIE_SECURE": "false",
            "NODE_ID": NODE_ID,
            "NODE_TOTAL_MEMORY_GB": "64",
        }
    )
    get_settings.cache_clear()

    # What the `migrate` service does after `alembic upgrade head`. The
    # applications deliberately write nothing at startup, so the test has to
    # provision the node the same way a deployment does.
    from app.infrastructure.provision import provision

    asyncio.run(provision())

    from app.infrastructure.main_admin_tailnet import create_app

    with TestClient(create_app()) as client:
        # Claims the administrator account, and seeds the CSRF companion
        # cookie: the tailnet entrance now carries the double-submit guard,
        # because `tailscale serve` attaches the identity header to any request
        # a hostile page can provoke. `COOKIE_SECURE=false` above drops the
        # `__Host-` prefix, so the cookie is `nexus_csrf` and travels over the
        # test client's http transport.
        client.get("/admin/me")
        client.headers["X-CSRF-Token"] = client.cookies["nexus_csrf"]
        yield client

    os.environ.clear()
    os.environ.update(previous)
    get_settings.cache_clear()


def _in_days(days: int) -> str:
    """A date the expiry rules will still accept when this is next run.

    Absolute dates in these bodies are a test that starts failing on a calendar
    day rather than on a change: expiry must be in the future and within a
    year, so `2026-12-31` is a pass that expires.
    """
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def _issue_key(admin: TestClient, **overrides: object) -> dict:
    users = admin.get("/admin/users").json()
    body: dict[str, object] = {
        "name": "editable",
        "owner_id": users[0]["id"],
        "scopes": ["chat"],
        "rate_limit_rpm": 60,
        "quota_tokens_per_day": 100000,
        "allowed_cidrs": [],
        "expires_at": _in_days(180),
    }
    body.update(overrides)
    issued = admin.post("/admin/api-keys", json=body)
    assert issued.status_code == 201, issued.text
    return issued.json()["key"]
