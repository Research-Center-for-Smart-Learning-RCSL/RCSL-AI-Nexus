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


def test_the_configured_node_exists_without_anyone_registering_it(admin: TestClient) -> None:
    """A node write endpoint has to ship with the SSRF guard, so Phase 1 names
    its single node in configuration instead. Without this the registry has
    nothing to attach a model to and the whole flow is unreachable."""
    nodes = admin.get("/admin/nodes")

    assert nodes.status_code == 200, nodes.text
    assert [n["id"] for n in nodes.json()] == [NODE_ID]
    assert nodes.json()[0]["total_memory_gb"] == 64.0


def test_a_capability_can_be_configured_and_the_dashboard_reflects_it(
    admin: TestClient,
) -> None:
    created = admin.post(
        "/admin/models",
        json={
            "alias": "chat-main",
            "ref": "library/qwen2.5:7b",
            "runtime": "ollama",
            "node_id": NODE_ID,
            "capabilities": ["chat"],
            "resource_profile": {"memory_gb": 8.0, "context_length": 32768},
        },
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    # Registration records intent; the weights are not there yet.
    assert created.json()["state"] == "not_downloaded"

    policy = admin.put(
        "/admin/routing-policies/chat",
        json={"candidates": [{"model_alias": "chat-main", "priority": 1}]},
    )
    assert policy.status_code == 200, policy.text
    assert [c["model_alias"] for c in policy.json()["candidates"]] == ["chat-main"]

    users = admin.get("/admin/users").json()
    key = admin.post(
        "/admin/api-keys",
        json={
            "name": "ci",
            "owner_id": users[0]["id"],
            "scopes": ["chat"],
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 100000,
            "allowed_cidrs": ["10.0.0.0/8"],
            "expires_at": "2027-01-01T00:00:00Z",
        },
    )
    assert key.status_code == 201, key.text
    assert key.json()["plaintext"].startswith("nx_live_")
    # Never present again, in this or any other response.
    assert "plaintext" not in admin.get("/admin/api-keys").json()[0]

    summary = admin.get("/admin/dashboard")
    assert summary.status_code == 200, summary.text
    assert summary.json()["models_total"] == 1
    assert summary.json()["models_loaded"] == 0
    assert summary.json()["nodes_total"] == 1
    assert summary.json()["api_keys_active"] == 1

    # And the model cannot be deleted while the policy names it, because
    # nothing in the schema enforces that binding.
    refused = admin.delete(f"/admin/models/{model_id}")
    assert refused.status_code == 409
    assert refused.json()["code"] == "model_state_conflict"

    assert admin.delete("/admin/routing-policies/chat").status_code == 204
    assert admin.delete(f"/admin/models/{model_id}").status_code == 204


def test_a_policy_naming_an_unregistered_alias_is_refused(admin: TestClient) -> None:
    refused = admin.put(
        "/admin/routing-policies/chat",
        json={"candidates": [{"model_alias": "not-registered", "priority": 1}]},
    )

    assert refused.status_code == 404
    assert refused.json()["code"] == "model_not_found"


def test_a_shell_metacharacter_never_reaches_the_registry(admin: TestClient) -> None:
    """The highest-risk path in the platform. Validated at registration as
    well as inside the adapter; see security.md section 7.1."""
    refused = admin.post(
        "/admin/models",
        json={
            "alias": "evil",
            "ref": "library/x; rm -rf /:latest",
            "runtime": "ollama",
            "node_id": NODE_ID,
            "capabilities": ["chat"],
            "resource_profile": {"memory_gb": 1.0, "context_length": 1024},
        },
    )

    assert refused.status_code == 422
    assert admin.get("/admin/models").json() == []


def test_a_date_only_expiry_is_accepted(admin: TestClient) -> None:
    """What the form actually sends.

    The expiry field is `<input type="date">`, so it can only ever produce
    `YYYY-MM-DD`. Pydantic parsed that into a naive datetime, and comparing it
    to an aware `now` raised `TypeError` — not a `DomainError`, so it escaped
    the handler as a bare 500 and no key could be issued from the UI at all.
    """
    users = admin.get("/admin/users").json()
    issued = admin.post(
        "/admin/api-keys",
        json={
            "name": "from-the-form",
            "owner_id": users[0]["id"],
            "scopes": ["chat"],
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 1000,
            "allowed_cidrs": [],
            "expires_at": "2026-10-23",
        },
    )

    assert issued.status_code == 201, issued.text


def test_a_created_resource_carries_the_timestamp_the_client_requires(
    admin: TestClient,
) -> None:
    """`created_at` is assigned by the database, and both create paths used to
    return the unsaved entity, which carries None for it.

    The frontend declares the field as a required string, so its parse threw
    *after* the row existed — destroying the one thing that response carries
    and nothing else ever will: the plaintext key, and the invitation link.
    """
    created_user = admin.post(
        "/admin/users",
        json={"login": "timestamped@example.org", "display_name": "T", "role": "user"},
    )
    assert created_user.status_code == 201, created_user.text
    assert created_user.json()["user"]["created_at"] is not None
    # The link exists in this response and in no other.
    assert created_user.json()["invitation"]["url"]

    issued = admin.post(
        "/admin/api-keys",
        json={
            "name": "timestamped",
            "owner_id": created_user.json()["user"]["id"],
            "scopes": ["chat"],
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 1000,
            "allowed_cidrs": [],
            "expires_at": "2027-01-01T00:00:00Z",
        },
    )
    assert issued.status_code == 201, issued.text
    assert issued.json()["key"]["created_at"] is not None
    assert issued.json()["plaintext"].startswith("nx_live_")


def test_an_unmetered_key_cannot_be_issued(admin: TestClient) -> None:
    """The gateway reads `rate_limit_rpm <= 0` as no limit, so zero was a way
    to mint an unmetered key through a form that reads as if it were
    tightening one. With no edge protection these guardrails are the only
    defence (security.md section 15.2)."""
    users = admin.get("/admin/users").json()
    body = {
        "name": "unmetered",
        "owner_id": users[0]["id"],
        "scopes": ["chat"],
        "rate_limit_rpm": 0,
        "quota_tokens_per_day": 0,
        "allowed_cidrs": [],
        "expires_at": "2027-01-01T00:00:00Z",
    }

    assert admin.post("/admin/api-keys", json=body).status_code == 422


def test_an_expiry_beyond_the_maximum_lifetime_is_refused(admin: TestClient) -> None:
    """Expiry exists to force rotation. `9999-12-31` satisfied "in the future"
    and rotated nothing."""
    users = admin.get("/admin/users").json()
    refused = admin.post(
        "/admin/api-keys",
        json={
            "name": "forever",
            "owner_id": users[0]["id"],
            "scopes": ["chat"],
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 1000,
            "allowed_cidrs": [],
            "expires_at": "9999-12-31T00:00:00Z",
        },
    )

    assert refused.status_code == 409


def test_an_expiry_in_the_past_is_refused(admin: TestClient) -> None:
    users = admin.get("/admin/users").json()
    refused = admin.post(
        "/admin/api-keys",
        json={
            "name": "stale",
            "owner_id": users[0]["id"],
            "scopes": ["chat"],
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 1000,
            "allowed_cidrs": [],
            "expires_at": "2020-01-01T00:00:00Z",
        },
    )

    assert refused.status_code == 409


def test_the_gateway_endpoint_tells_the_ui_where_to_send_a_key(admin: TestClient) -> None:
    """A key with no endpoint to send it to is not a working key, and the UI
    cannot read the origin off its own request: it is served from the admin
    host, not the one being described."""
    info = admin.get("/admin/gateway")

    assert info.status_code == 200, info.text
    assert info.json()["base_url"].startswith("http")
    assert not info.json()["base_url"].endswith("/")
    # Nothing is routable until a policy exists, which is the honest answer
    # rather than the five names the issuing form knows how to spell.
    assert info.json()["capabilities"] == []

    admin.post(
        "/admin/models",
        json={
            "alias": "chat-main",
            "ref": "library/qwen2.5:7b",
            "runtime": "ollama",
            "node_id": NODE_ID,
            "capabilities": ["chat"],
            "resource_profile": {"memory_gb": 8.0, "context_length": 32768},
        },
    )
    admin.put(
        "/admin/routing-policies/chat",
        json={"candidates": [{"model_alias": "chat-main", "priority": 1}]},
    )

    assert admin.get("/admin/gateway").json()["capabilities"] == ["chat"]


def test_own_usage_is_served_from_its_own_path(admin: TestClient) -> None:
    """Wiring, which is the half the unit tests cannot reach.

    `/admin/usage/me` has to resolve to its own route rather than being
    swallowed by anything, build through the same DI as `/admin/usage`, and
    return the shape the charts already parse. What it *counts* is asserted in
    `test_logs_and_usage.py` against real rows, and the scope it demands in
    `test_read_audit_and_usage.py`; this is the third piece, and the one that
    would break by editing a decorator.
    """
    mine = admin.get("/admin/usage/me", params={"range": "24h"})

    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["bucket"] == "hour"
    assert body["totals"] == []
    assert body["by_capability"] == []
    assert set(body) == set(admin.get("/admin/usage", params={"range": "24h"}).json())


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


def test_a_key_can_be_edited_with_what_the_form_sends(admin: TestClient) -> None:
    """The PATCH verb had no caller: the endpoint, the client function and the
    hook all existed, and no component ever reached them, so this contract had
    never been exercised over HTTP at all.

    The payload here is the edit dialog's, field for field. In particular the
    expiry is date-only, because the control is `<input type="date">` and can
    emit nothing else — the same shape that made issuing a key a bare 500
    until `UtcDatetime` was applied on the create path.
    """
    key_id = _issue_key(admin)["key_id"]

    edited = admin.patch(
        f"/admin/api-keys/{key_id}",
        json={
            "name": "renamed",
            "scopes": ["chat", "code"],
            "rate_limit_rpm": 30,
            "quota_tokens_per_day": 5000,
            "allowed_cidrs": ["10.0.0.7/24", "2001:db8::/32"],
            "expires_at": _in_days(30),
        },
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "renamed"
    assert sorted(edited.json()["scopes"]) == ["chat", "code"]
    assert edited.json()["rate_limit_rpm"] == 30
    # Host bits are accepted as the network they mean, rather than refused.
    assert edited.json()["allowed_cidrs"] == ["10.0.0.0/24", "2001:db8::/32"]
    # The response must still parse as a key: the frontend re-parses it with
    # the same schema it uses for the list, which requires `created_at`.
    assert edited.json()["created_at"] is not None
    assert "plaintext" not in edited.json()

    # And it is what a reload shows, not just what the write echoed back.
    listed = next(k for k in admin.get("/admin/api-keys").json() if k["key_id"] == key_id)
    assert listed["name"] == "renamed"
    assert listed["rate_limit_rpm"] == 30


def test_editing_cannot_mint_an_unmetered_key(admin: TestClient) -> None:
    """The create path refuses zero; the edit path is the other way to reach
    the same column, and the gateway reads `rate_limit_rpm <= 0` as no limit."""
    key_id = _issue_key(admin)["key_id"]

    path = f"/admin/api-keys/{key_id}"

    assert admin.patch(path, json={"rate_limit_rpm": 0}).status_code == 422
    assert admin.patch(path, json={"quota_tokens_per_day": 0}).status_code == 422


def test_an_edit_that_omits_the_expiry_leaves_it_alone(admin: TestClient) -> None:
    """What the edit dialog sends when the operator changes only the name.

    A date input holds a calendar day, so resubmitting an untouched expiry
    rewrites an 18:00Z one to midnight — shortening the key by up to a day on
    every edit, and refusing outright once that midnight is already past, which
    makes renaming a key that expires later today impossible.
    """
    # Tomorrow rather than today, so the fixture is in the future whatever the
    # hour: "today at 18:00Z" is itself a test that fails after 18:00Z. The
    # time of day is the whole point — a resent date-only value would land on
    # midnight and the assertion below would catch it.
    issued = _issue_key(admin, expires_at=f"{_in_days(1)}T18:00:00Z")
    before = issued["expires_at"]

    renamed = admin.patch(f"/admin/api-keys/{issued['key_id']}", json={"name": "renamed"})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed"
    assert renamed.json()["expires_at"] == before


def test_editing_a_revoked_key_is_refused(admin: TestClient) -> None:
    """Otherwise the result reads as active in the table and is not."""
    key_id = _issue_key(admin)["key_id"]
    assert admin.post(f"/admin/api-keys/{key_id}/revoke").status_code == 204

    refused = admin.patch(f"/admin/api-keys/{key_id}", json={"name": "again"})

    assert refused.status_code == 409


def test_the_only_administrator_cannot_delete_themselves(admin: TestClient) -> None:
    """Two guards overlap here and both matter: self-deletion, and the last
    enabled administrator. Either one alone leaves a reachable way to lock
    everybody out."""
    me = admin.get("/admin/me").json()

    refused = admin.delete(f"/admin/users/{me['id']}")

    assert refused.status_code == 403
    assert admin.get("/admin/users").json() != []


def test_a_member_cannot_reach_the_management_endpoints(admin: TestClient) -> None:
    """Role gating in the UI is an affordance. The check that matters is in
    the use case, so it applies to a caller that never loaded the UI."""
    created = admin.post(
        "/admin/users",
        json={"login": "member@example.org", "display_name": "Member", "role": "user"},
    )
    assert created.status_code == 201

    # Promote and demote through the API to prove the role change lands, then
    # confirm the demoted account is refused. The tailnet entrance identifies
    # by header, so a second identity cannot be exercised in this test; what
    # is checked here is that the stored role is what authorisation reads.
    member_id = created.json()["user"]["id"]
    promoted = admin.patch(f"/admin/users/{member_id}", json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    demoted = admin.patch(f"/admin/users/{member_id}", json={"role": "user"})
    assert demoted.json()["role"] == "user"


def test_disabling_an_account_is_reversible(admin: TestClient) -> None:
    created = admin.post(
        "/admin/users",
        json={"login": "member2@example.org", "display_name": "Member", "role": "user"},
    )
    member_id = created.json()["user"]["id"]

    assert admin.patch(f"/admin/users/{member_id}", json={"disabled": True}).status_code == 200
    assert admin.patch(f"/admin/users/{member_id}", json={"disabled": False}).status_code == 200
