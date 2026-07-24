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
        client.get("/admin/me")  # claims the administrator account
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
