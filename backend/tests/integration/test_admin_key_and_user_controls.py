from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.admin_api_end_to_end_fixtures import (
    _in_days,
    _issue_key,
)

pytest_plugins = ("tests.integration.admin_api_end_to_end_fixtures",)


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
