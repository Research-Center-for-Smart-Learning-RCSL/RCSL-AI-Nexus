from __future__ import annotations

import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from tests.integration.admin_api_end_to_end_fixtures import (
    NODE_ID,
)

pytest_plugins = ("tests.integration.admin_api_end_to_end_fixtures",)


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


def test_the_windows_tools_download_from_the_platform_that_issued_the_key(
    admin: TestClient,
) -> None:
    """The other half of the same answer as `/admin/gateway`.

    That one says where to send a key; this hands over the scripts that put the
    key into the Windows App. It is served here rather than as a link to a
    GitHub branch so that the bytes come from the deployed image, over the
    origin and session the operator is already trusting, and so that the
    operator path does not quietly break if the repository stops being public.
    """
    response = admin.get("/admin/client-tools/windows-codex-app")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "rcsl-codex-app-tools.zip" in response.headers["content-disposition"]

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())

    # The switcher without the module it imports is a download that fails on the
    # operator's machine rather than here.
    assert {"Start-CodexAppSwitcher.ps1", "CodexAppSwitcher.Common.psm1"} <= names


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
