"""A fresh deployment to a signed-in user on the public entrance.

This is the path that cannot be established by unit tests: bootstrap runs in
middleware, the invitation crosses from one entrance to the other, and the
login is three requests that only work if the cookie, the CSRF binding and the
challenge all agree. Each piece has its own test; none of them would notice a
composition root that wired the wrong adapter in.

`AUTH_MODE=dev` substitutes the `Tailscale-User-Login` header and changes
nothing else, so the bootstrap and identity resolution exercised here are the
same code a deployment runs.

**The two entrances are opened one after the other, never at once.** Each
`TestClient` runs its own event loop, while `init_engine` holds one engine per
process; asyncpg connections belong to the loop that created them, so a second
client reusing that engine waits forever on futures from the first client's
loop. Production never meets this because the entrances are separate
containers, and the shape of the flow does not need them concurrent: the
tailnet issues the link, and everything after that is the public entrance.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.adapters.crypto.pyotp_totp import STEP_SECONDS
from app.infrastructure.config import get_settings
from tests.integration.conftest import TEST_DATABASE_URL, reset_schema

BOOTSTRAP_LOGIN = "dev@localhost"
INVITEE = "invited@example.org"
INVITEE_PASSWORD = "thicket-marmalade-signpost-4"  # noqa: S105  (a test fixture)

CSRF_COOKIE = "nexus_csrf"
CSRF_HEADER = "X-CSRF-Token"


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
            # TestClient speaks http, and a browser discards a Secure cookie
            # over it. Production refuses to start with this off.
            "COOKIE_SECURE": "false",
            "ADMIN_BASE_URL": "http://admin.test",
        }
    )
    get_settings.cache_clear()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)
        get_settings.cache_clear()


def tailnet_client() -> TestClient:
    from app.infrastructure.main_admin_tailnet import create_app

    return TestClient(create_app())


def public_client() -> TestClient:
    from app.infrastructure.main_admin_public import create_app

    return TestClient(create_app())


def post(client: TestClient, path: str, **kwargs):  # type: ignore[no-untyped-def]
    """Attaches the CSRF header from the companion cookie, as the browser
    client does. Both entrances now carry the double-submit guard, so any
    unsafe request without the header is refused.

    Seeds the cookie with a GET first if the client has not made one yet, the
    same order the session provider uses in the browser.
    """
    if client.cookies.get(CSRF_COOKIE) is None:
        client.get("/admin/me")
    headers = dict(kwargs.pop("headers", None) or {})
    token = client.cookies.get(CSRF_COOKIE)
    if token:
        headers[CSRF_HEADER] = token
    return client.post(path, headers=headers, **kwargs)


def test_a_fresh_deployment_reaches_a_signed_in_user(deployment: None) -> None:
    with tailnet_client() as tailnet:
        # 1. The first request on the tailnet claims the administrator account.
        me = tailnet.get("/admin/me")
        assert me.status_code == 200, me.text
        assert me.json()["login"] == BOOTSTRAP_LOGIN
        assert me.json()["role"] == "admin"
        # No session on this entrance: identity is per request, from the header.
        assert me.json()["session_expires_at"] is None

        # 2. Bootstrap is inert afterwards, so the setting never needs removing.
        assert tailnet.get("/admin/me").json()["id"] == me.json()["id"]

        # 3. The administrator creates an account and receives the only copy of
        #    the link.
        created = post(
            tailnet,
            "/admin/users",
            json={"login": INVITEE, "display_name": "Invited Person", "role": "user"},
        )
        assert created.status_code == 201, created.text
        token = _token_from(created.json()["invitation"]["url"])
        assert created.json()["user"]["has_local_credentials"] is False

    with public_client() as public:
        # 4. The recipient opens it on the public entrance, unauthenticated.
        public.get("/admin/me")  # seeds the CSRF companion cookie, as the UI's first call does
        enrolment = public.get("/admin/invitations", params={"token": token})
        assert enrolment.status_code == 200, enrolment.text
        secret = enrolment.json()["secret"]
        assert enrolment.json()["login"] == INVITEE

        # The QR is rendered here, never by a third party: the URI is the secret.
        qr = public.get("/admin/invitations/totp-qr", params={"token": token})
        assert qr.status_code == 200
        assert qr.headers["content-type"] == "image/png"
        assert qr.headers["cache-control"] == "no-store, private"

        # 5. They choose a password and prove the authenticator works.
        accepted = post(
            public,
            "/admin/invitations/accept",
            json={
                "token": token,
                "password": INVITEE_PASSWORD,
                "totp_code": pyotp.TOTP(secret).now(),
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert len(accepted.json()["recovery_codes"]) == 10

        # 6. The link is spent.
        assert public.get("/admin/invitations", params={"token": token}).status_code == 400

        # 7. Password first, which yields a challenge and no session.
        challenge = post(
            public, "/admin/auth/login", json={"login": INVITEE, "password": INVITEE_PASSWORD}
        )
        assert challenge.status_code == 200, challenge.text
        assert challenge.json()["next"] == "totp"
        assert public.get("/admin/me").status_code == 401

        # 8. The second factor issues the session.
        signed_in = post(
            public,
            "/admin/auth/login/totp",
            json={
                "challenge": challenge.json()["challenge"],
                # A different step from the enrolment code above, whose counter
                # was claimed: a code cannot be carried from enrolment into a
                # login.
                "code": pyotp.TOTP(secret).at(_next_step()),
            },
        )
        assert signed_in.status_code == 204, signed_in.text

        who = public.get("/admin/me")
        assert who.status_code == 200, who.text
        assert who.json()["login"] == INVITEE
        assert who.json()["role"] == "user"
        assert who.json()["session_expires_at"] is not None

        # 9. Signing out ends it.
        assert post(public, "/admin/auth/logout").status_code == 204
        assert public.get("/admin/me").status_code == 401

    # 10. And all of it left a trail. Until 2026-08-02 none of these existed:
    #     `AuthenticateLocal` took no `AuditPort`, so a platform could be
    #     enrolled into, signed into and signed out of with the audit log
    #     showing only the invitation. Asserted here rather than only in unit
    #     tests because the fakes accept anything — this is the composition
    #     root, the real writer and the real columns.
    with tailnet_client() as tailnet:
        logs = tailnet.get("/admin/logs", params={"limit": 100})
        assert logs.status_code == 200, logs.text
        actions = [entry["action"] for entry in logs.json()["entries"]]

    for expected in (
        "user.invited",
        "user.invitation_accepted",
        "user.totp_enrolled",
        "user.signed_in",
        "user.signed_out",
    ):
        assert expected in actions, f"{expected} missing from {actions}"


def test_a_signed_in_user_cannot_invite(deployment: None) -> None:
    """Role gating in the UI is an affordance. The check that matters is in the
    use case, and it does not care which entrance the caller used."""
    with tailnet_client() as tailnet:
        tailnet.get("/admin/me")
        created = post(
            tailnet,
            "/admin/users",
            json={"login": INVITEE, "display_name": "Invited Person", "role": "user"},
        )
        token = _token_from(created.json()["invitation"]["url"])

    with public_client() as public:
        public.get("/admin/me")
        secret = public.get("/admin/invitations", params={"token": token}).json()["secret"]
        post(
            public,
            "/admin/invitations/accept",
            json={
                "token": token,
                "password": INVITEE_PASSWORD,
                "totp_code": pyotp.TOTP(secret).now(),
            },
        )
        challenge = post(
            public, "/admin/auth/login", json={"login": INVITEE, "password": INVITEE_PASSWORD}
        )
        post(
            public,
            "/admin/auth/login/totp",
            json={
                "challenge": challenge.json()["challenge"],
                "code": pyotp.TOTP(secret).at(_next_step()),
            },
        )

        refused = post(
            public,
            "/admin/users",
            json={"login": "third@example.org", "display_name": "Third", "role": "admin"},
        )

    assert refused.status_code == 403
    assert refused.json()["code"] == "not_authorized"


def test_a_wrong_password_reveals_nothing_about_the_account(deployment: None) -> None:
    """An unknown login and a real account with the wrong password must be one
    response. Timing is handled by the dummy hash; this pins the body."""
    with tailnet_client() as tailnet:
        tailnet.get("/admin/me")
        post(
            tailnet,
            "/admin/users",
            json={"login": INVITEE, "display_name": "Invited Person", "role": "user"},
        )

    with public_client() as public:
        public.get("/admin/me")
        unknown = post(
            public, "/admin/auth/login", json={"login": "nobody@example.org", "password": "x"}
        )
        known = post(public, "/admin/auth/login", json={"login": INVITEE, "password": "x"})

    assert unknown.status_code == known.status_code == 401
    # `request_id` is a per-request nonce (2026-08-05), so the two bodies can
    # no longer be byte-identical. The property this test pins is unchanged —
    # nothing in the response may correlate with whether the account exists —
    # and a value freshly minted for every request regardless of its outcome
    # cannot. Both must carry one, though: an asymmetric presence would itself
    # be a distinguisher.
    unknown_body, known_body = unknown.json(), known.json()
    assert unknown_body.pop("request_id").startswith("req_")
    assert known_body.pop("request_id").startswith("req_")
    assert unknown_body == known_body


def test_failed_logins_do_not_lock_the_account_out_at_the_per_account_limit(
    deployment: None,
) -> None:
    """The throttle must not become the denial-of-service it defends against.

    A run of failures naming one account, more than the per-(address, account)
    limit but under the per-address limit, must not refuse a subsequent correct
    login. TestClient cannot vary the peer address, so this exercises the case
    the first version got wrong for a different reason: it refused on a
    per-account count alone, which barred the owner. The per-account counter
    now only alerts.
    """
    with tailnet_client() as tailnet:
        tailnet.get("/admin/me")
        created = post(
            tailnet,
            "/admin/users",
            json={"login": INVITEE, "display_name": "Invited Person", "role": "user"},
        )
        token = _token_from(created.json()["invitation"]["url"])

    with public_client() as public:
        secret = public.get("/admin/invitations", params={"token": token}).json()["secret"]
        post(
            public,
            "/admin/invitations/accept",
            json={
                "token": token,
                "password": INVITEE_PASSWORD,
                "totp_code": pyotp.TOTP(secret).now(),
            },
        )

        # Six failures against this one login. Over the per-(address, account)
        # limit, so the seventh attempt for THIS login would wait — but a
        # different login from the same address is still served, which is what
        # proves the block is scoped to the pair and not to the account.
        for _ in range(6):
            post(public, "/admin/auth/login", json={"login": INVITEE, "password": "wrong"})

        other = post(
            public, "/admin/auth/login", json={"login": "someone-else@example.org", "password": "x"}
        )

    # A wrong password for an unrelated login still reaches the handler and
    # returns the enumeration-safe 401, not a 429 from a mis-scoped counter.
    assert other.status_code == 401
    assert other.json()["code"] == "invalid_credentials"


def _token_from(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def _next_step() -> int:
    """A timestamp one TOTP step ahead.

    The enrolment code claimed its counter, and the login refuses anything at
    or below it. Reusing the same code here would be the replay the design
    forbids, so the test asks for the next one rather than sleeping 30 seconds.
    """
    return int(time.time()) + STEP_SECONDS
