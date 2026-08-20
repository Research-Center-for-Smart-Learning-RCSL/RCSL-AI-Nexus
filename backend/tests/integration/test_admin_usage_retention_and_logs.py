from __future__ import annotations

from fastapi.testclient import TestClient

pytest_plugins = ("tests.integration.admin_api_end_to_end_fixtures",)


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


def test_retention_is_configurable_and_purges_what_it_says(admin: TestClient) -> None:
    """The wiring, over HTTP, against the real table.

    What the unit tests cannot reach: that the migration ran, that the upsert
    round-trips, and that a purge aimed at one dataset reports the same number
    it deleted. The audit trail is the observable side — this deployment writes
    an entry per request, so purging `usage_records` leaves entries behind and
    the count is checkable.
    """
    defaults = admin.get("/admin/retention")
    assert defaults.status_code == 200, defaults.text
    by_dataset = {p["dataset"]: p for p in defaults.json()}
    assert set(by_dataset) == {"audit_log", "usage_records", "prompt_logs", "refusals"}
    assert by_dataset["audit_log"]["days"] == 360
    assert by_dataset["usage_records"]["days"] == 360
    # Markedly shorter, and not by convention: section 9.2 requires it and the
    # bounds table makes it the default nobody has to remember to set.
    assert by_dataset["prompt_logs"]["days"] == 7
    assert all(p["updated_by"] is None for p in defaults.json())

    saved = admin.put("/admin/retention/usage_records", json={"days": 90})
    assert saved.status_code == 200, saved.text
    assert saved.json()["days"] == 90
    assert saved.json()["updated_by"]

    # Read back through a second request, so this is the stored row rather than
    # the one just constructed in memory.
    stored = {p["dataset"]: p for p in admin.get("/admin/retention").json()}
    assert stored["usage_records"]["days"] == 90
    assert stored["audit_log"]["days"] == 360, "the other dataset is untouched"

    # Nothing here is 90 days old, so the honest answer to both is zero.
    preview = admin.get("/admin/retention/usage_records/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"dataset": "usage_records", "days": 90, "affected": 0}

    purged = admin.post("/admin/retention/usage_records/purge")
    assert purged.status_code == 200, purged.text
    assert purged.json()["deleted"] == 0
    assert purged.json()["cutoff"]


def test_a_window_under_the_floor_is_refused_over_http(admin: TestClient) -> None:
    refused = admin.put("/admin/retention/audit_log", json={"days": 7})
    assert refused.status_code == 400, refused.text
    assert admin.get("/admin/retention").json()[0]["days"] == 360


def test_a_prompt_log_window_over_the_ceiling_is_refused_over_http(
    admin: TestClient,
) -> None:
    """The bound that runs the other way, end to end.

    `audit_log` refuses a window that is too short; `prompt_logs` refuses one
    that is too long. Both are 400s and they carry different codes, because a
    client that collapsed them would give the same advice for two opposite
    problems.
    """
    refused = admin.put("/admin/retention/prompt_logs", json={"days": 365})
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "retention_window_too_long"

    stored = {p["dataset"]: p for p in admin.get("/admin/retention").json()}
    assert stored["prompt_logs"]["days"] == 7, "the refused number did not land"

    accepted = admin.put("/admin/retention/prompt_logs", json={"days": 14})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["days"] == 14


def test_the_transcript_routes_are_reachable_and_empty_by_default(
    admin: TestClient,
) -> None:
    """The wiring, and the default state that matters most.

    An empty list on a deployment nobody has opened a window on is the whole of
    section 9.2's promise: metadata by default, full text only while a named
    credential's window is open. This asserts it over HTTP, from the outside,
    where a regression would otherwise be invisible until somebody read the
    table by hand.
    """
    listed = admin.get("/admin/prompt-logs")

    assert listed.status_code == 200, listed.text
    assert listed.json() == {"entries": [], "total": 0, "limit": 50, "offset": 0}


def test_a_refusal_reaches_the_table_and_comes_back_with_its_figure(
    admin: TestClient,
) -> None:
    """The whole of the feature, over HTTP, on the refusal that cost an evening.

    An expiry beyond the maximum is refused with a 409 whose reason lived in
    `detail` — which does not leave the process — so what the operator saw was a
    save that failed with no subject, immediately after editing a capability
    list, and they read it as the capability edit being rejected. Seven attempts
    in three minutes.

    Now the same refusal is stored as what they were told, and they can read it
    back without an administrator opening a container log. `maximum_days` is
    there because a published policy is not inventory, and it is the figure that
    ends this particular evening.
    """
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
    assert refused.status_code == 409, refused.text

    listed = admin.get("/admin/refusals", params={"code": "api_key_lifetime"})

    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] >= 1
    stored = page["entries"][0]
    assert stored["status"] == 409
    assert stored["figures"]["maximum_days"] == 365
    # The route as declared, so a hundred refusals on this endpoint group
    # instead of scattering, and nothing a caller put in a path is kept.
    assert stored["path"] == "/admin/api-keys"
    assert stored["request_id"] == refused.json()["request_id"]
    # `detail` names the date they typed and is operator-facing; it must not be
    # in a row its own subject may read.
    assert "9999" not in stored["message"]


def test_the_refusals_a_caller_may_read_are_theirs_unless_a_scope_says_otherwise(
    admin: TestClient,
) -> None:
    """The administrator here holds `refusal:read_all`, so the page says it is
    not narrowed. The narrowing itself is unit-tested; what this pins is that
    the flag survives the wire, because it is what the screen reads to decide
    whether to tell the reader they are seeing a subset."""
    page = admin.get("/admin/refusals").json()

    assert page["scoped_to_self"] is False
    assert set(page) == {"entries", "total", "limit", "offset", "scoped_to_self"}


def test_reading_a_transcript_that_does_not_exist_is_a_404(admin: TestClient) -> None:
    """And not a 403. The repository is tenant-scoped, so another tenant's id
    and an expired one and an invented one all read alike — answering
    "forbidden" would confirm the row exists."""
    missing = admin.get("/admin/prompt-logs/nope")

    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "prompt_log_not_found"


def test_an_unknown_dataset_is_not_reachable(admin: TestClient) -> None:
    """The enum is the allowlist. A table name taken from the caller is the
    shape of this feature that would have been a very bad idea."""
    assert admin.get("/admin/retention/users/preview").status_code == 422
    assert admin.post("/admin/retention/users/purge").status_code == 422
