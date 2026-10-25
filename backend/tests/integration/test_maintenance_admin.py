"""Closing and reopening the platform through the admin entrances (#61).

The path walked here is the one #61's acceptance names: a signed-in user is
thrown out when an administrator closes the platform, cannot sign back in
while it is closed (not even by finishing a login begun before it closed),
stays signed out after it reopens, and can then sign in again. The
administrator keeps the management screens throughout and loses the models.

The entrances are opened one at a time, for the reason `test_auth_end_to_end`
gives; cookies are carried between clients by hand.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.config import get_settings
from tests.integration.conftest import TEST_DATABASE_URL, reset_schema
from tests.integration.test_auth_end_to_end import (
    BOOTSTRAP_LOGIN,
    CSRF_COOKIE,
    _next_step,
    _token_from,
    post,
    public_client,
    tailnet_client,
)

INVITEE = "researcher@example.org"
INVITEE_PASSWORD = "lantern-quarry-pebble-9"  # noqa: S105  (a test fixture)


@pytest.fixture
def deployment() -> Iterator[None]:
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
            "ADMIN_BASE_URL": "http://admin.test",
            "MAINTENANCE_ENABLED": "true",
        }
    )
    get_settings.cache_clear()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)
        get_settings.cache_clear()


def _hold(closed: bool) -> None:
    """The row as `ManageMaintenance` writes it, from outside the app.

    The public entrance's sessions live in the app's in-process cache in these
    tests, so its client has to stay open from sign-in to the end, and the
    tailnet entrance cannot be opened beside it (see `test_auth_end_to_end`).
    The routes that write this row are walked in the test below this one.
    """

    async def write() -> None:
        engine = create_async_engine(TEST_DATABASE_URL or "")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE maintenance_control SET admission_closed = :closed, "
                    "phase = CASE WHEN :closed THEN 'maintenance' ELSE 'normal' END, "
                    "message = CASE WHEN :closed THEN 'Upgrading the runtime' END, "
                    "epoch = epoch + CASE WHEN :closed THEN 1 ELSE 0 END, "
                    "revision = revision + 1 WHERE id = 1"
                ),
                {"closed": closed},
            )
        await engine.dispose()

    asyncio.run(write())


def _enrol_and_sign_in(public: TestClient, token: str) -> list[str]:
    """Signs in by TOTP and returns the recovery codes. Later logins in the test
    use those: a TOTP code is valid one step either side of now, and this
    login has already claimed the newest step."""
    public.get("/admin/me")
    secret = public.get("/admin/invitations", params={"token": token}).json()["secret"]
    accepted = post(
        public,
        "/admin/invitations/accept",
        json={"token": token, "password": INVITEE_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert accepted.status_code == 200, accepted.text
    codes: list[str] = accepted.json()["recovery_codes"]
    challenge = post(
        public, "/admin/auth/login", json={"login": INVITEE, "password": INVITEE_PASSWORD}
    ).json()["challenge"]
    signed_in = post(
        public,
        "/admin/auth/login/totp",
        json={"challenge": challenge, "code": pyotp.TOTP(secret).at(_next_step())},
    )
    assert signed_in.status_code == 204, signed_in.text
    assert public.get("/admin/me").status_code == 200
    return codes


def test_closing_the_platform_signs_users_out_for_good(deployment: None) -> None:
    with tailnet_client() as tailnet:
        created = post(
            tailnet,
            "/admin/users",
            json={"login": INVITEE, "display_name": "Researcher", "role": "user"},
        )
        assert created.status_code == 201, created.text
        token = _token_from(created.json()["invitation"]["url"])

    with public_client() as public:
        codes = _enrol_and_sign_in(public, token)
        # A second login begun before the platform closes, finished after.
        pending = post(
            public, "/admin/auth/login", json={"login": INVITEE, "password": INVITEE_PASSWORD}
        ).json()["challenge"]
        before = public.get("/admin/maintenance/status").json()
        assert before["closed"] is False
        assert before["message"] is None

        _hold(True)

        # Anonymous: closed, the message, nothing about who or why.
        status = public.get("/admin/maintenance/status").json()
        assert status["closed"] is True
        assert status["message"] == "Upgrading the runtime"
        assert set(status) == {"closed", "phase", "message", "expected_return_at", "revision"}

        # The signed-in user is out, and told why rather than told to log in.
        me = public.get("/admin/me")
        assert me.status_code == 503, me.text
        assert me.json()["code"] == "maintenance"

        # The login begun before the hold cannot be finished during it, by
        # either second factor.
        finished = post(
            public,
            "/admin/auth/login/recovery-code",
            json={"challenge": pending, "recovery_code": codes[0]},
        )
        assert finished.status_code == 503, finished.text
        assert finished.json()["code"] == "maintenance"

        _hold(False)

        # Still signed out: reopening does not bring the session back.
        assert public.get("/admin/me").status_code == 401
        challenge = post(
            public, "/admin/auth/login", json={"login": INVITEE, "password": INVITEE_PASSWORD}
        ).json()["challenge"]
        signed_in = post(
            public,
            "/admin/auth/login/recovery-code",
            json={"challenge": challenge, "recovery_code": codes[1]},
        )
        assert signed_in.status_code == 204, signed_in.text
        assert public.get("/admin/me").status_code == 200


def test_an_administrator_closes_keeps_management_and_loses_the_models(
    deployment: None,
) -> None:
    with tailnet_client() as tailnet:
        entered = post(
            tailnet,
            "/admin/maintenance/enter",
            json={"message": "Upgrading the runtime", "expected_return_at": None},
        )
        assert entered.status_code == 200, entered.text
        assert entered.json()["closed"] is True
        assert entered.json()["epoch"] == 1

        # Pressed again: the same hold, not a second epoch or a new message.
        again = post(tailnet, "/admin/maintenance/enter", json={"message": "twice"})
        assert again.status_code == 200
        assert again.json()["epoch"] == 1
        assert again.json()["message"] == "Upgrading the runtime"

        # The administrator keeps the management screens...
        assert tailnet.get("/admin/me").status_code == 200
        assert tailnet.get("/admin/users").status_code == 200
        assert tailnet.get("/admin/maintenance").json()["changed_by"] is not None
        # ...and loses the models, like everybody else.
        chat = post(
            tailnet,
            "/admin/chat",
            json={"model": "chat", "messages": [{"role": "user", "content": "x"}]},
        )
        assert chat.status_code == 503, chat.text
        assert chat.json()["code"] == "maintenance"
        assert chat.headers["Retry-After"] == "60"
        assert post(tailnet, "/admin/knowledge/search", json={"query": "x"}).status_code == 503

        # A stale message edit is refused rather than overwriting a newer one.
        stale = tailnet.put(
            "/admin/maintenance/message",
            json={"message": "old", "expected_revision": 0},
            headers={"X-CSRF-Token": tailnet.cookies[CSRF_COOKIE]},
        )
        assert stale.status_code == 409, stale.text

        reopened = post(tailnet, "/admin/maintenance/reopen")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["closed"] is False
        assert reopened.json()["epoch"] == 1

        entries = tailnet.get("/admin/logs", params={"limit": 100}).json()["entries"]
        actions = [entry["action"] for entry in entries]
        assert "maintenance.entered" in actions
        assert "maintenance.reopened" in actions


def test_entering_is_refused_while_the_feature_is_off(deployment: None) -> None:
    os.environ["MAINTENANCE_ENABLED"] = "false"
    get_settings.cache_clear()
    with tailnet_client() as tailnet:
        refused = post(tailnet, "/admin/maintenance/enter", json={})
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "maintenance_disabled"
        assert tailnet.get("/admin/maintenance").json()["enabled"] is False
        # Reopening is never refused, so a hold can always be lifted.
        assert post(tailnet, "/admin/maintenance/reopen").status_code == 200


def test_a_tailnet_user_who_is_not_a_platform_admin_is_held_out(deployment: None) -> None:
    """The tailnet has no session to revoke, so the hold refuses the identity
    on every request instead. A tenant administrator is held out like anyone
    else below `admin`, and its Tailscale account is untouched."""
    with tailnet_client() as tailnet:
        created = post(
            tailnet,
            "/admin/users",
            json={"login": "lead@example.org", "display_name": "Lead", "role": "tenant_admin"},
        )
        assert created.status_code == 201, created.text

    # Only the bootstrap administrator is given a tailnet login by the platform;
    # an operator maps the others by hand, which is what this stands in for.
    async def map_tailnet_login() -> None:
        engine = create_async_engine(TEST_DATABASE_URL or "")
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE users SET tailscale_login = login WHERE login = 'lead@example.org'")
            )
        await engine.dispose()

    asyncio.run(map_tailnet_login())
    os.environ["DEV_TAILNET_LOGIN"] = "lead@example.org"
    get_settings.cache_clear()
    with tailnet_client() as tailnet:
        assert tailnet.get("/admin/me").status_code == 200
        _hold(True)
        held = tailnet.get("/admin/me")
        assert held.status_code == 503, held.text
        assert held.json()["code"] == "maintenance"
        _hold(False)
        assert tailnet.get("/admin/me").status_code == 200
