from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.exceptions import (
    NoAvailableModelError,
    QuotaExceededError,
)
from app.infrastructure.config import get_settings
from app.interfaces.http import request_context
from tests.unit.error_precision_fixtures import (
    _app,
    _quota_body,
)

pytest_plugins = ("tests.unit.error_precision_fixtures",)


def test_every_response_carries_a_request_id_header() -> None:
    client = TestClient(_app("openai"))
    response = client.get("/fails")
    assert response.headers["X-Request-Id"].startswith("req_")


def test_the_error_body_repeats_the_header_id() -> None:
    """Bodies get pasted into bug reports; headers do not. The two must be the
    same id or the correlation the pair exists for breaks."""
    client = TestClient(_app("openai"))
    response = client.get("/fails")
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


def test_a_500_is_json_with_an_envelope_and_the_id() -> None:
    """Until 2026-08-05 this was the framework's bare text — the one non-JSON
    body the API produced, on the status where a client most needs to parse."""
    client = TestClient(_app("openai"), raise_server_exceptions=False)
    response = client.get("/explodes")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"].startswith("req_")
    assert response.headers["X-Request-Id"] == body["error"]["request_id"]


def test_a_spent_quota_is_not_typed_as_a_rate_limit() -> None:
    """429 carries two conditions with opposite remedies. `code` has always
    distinguished them and `type` did not, which left every OpenAI client
    library — they select their error class from `type` — retrying a budget
    that no amount of waiting inside the hour would return."""
    body, _ = _quota_body(retry_after_seconds=3000)
    assert body["error"]["type"] == "insufficient_quota"
    # The code is the stable half of the pair and must not move with the type.
    assert body["error"]["code"] == "quota_exceeded"


def test_a_spent_quota_carries_the_wait_the_window_actually_implies() -> None:
    body, headers = _quota_body(retry_after_seconds=61_200)
    assert headers["retry-after"] == "61200"
    assert "about 17 hours" in body["error"]["message"]


def test_an_unprojectable_wait_sends_no_retry_after_at_all() -> None:
    """The fixed hour this replaced was worse than nothing: a client that
    believed it retried eleven times too early and learned nothing each time."""
    body, headers = _quota_body()
    assert "retry-after" not in headers
    assert body["error"]["message"] == QuotaExceededError.public_message


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (45, "a moment"),
        (600, "about 10 minutes"),
        (3540, "about 59 minutes"),
        (3600, "about an hour"),
        (86_400, "about 24 hours"),
    ],
)
def test_the_wait_is_rounded_to_something_a_person_can_act_on(seconds: int, expected: str) -> None:
    """A projection off a rolling window is not precise, and quoting it to the
    second would claim it is. The next request against the same key moves it."""
    message = QuotaExceededError(retry_after_seconds=seconds).public_message
    assert message.endswith(f"It recovers in {expected}.")


def test_detail_stays_out_of_the_body_without_a_debug_window() -> None:
    client = TestClient(_app("openai"))
    body = client.get("/fails").json()
    assert "operator-facing context" not in str(body)


def test_an_open_debug_window_puts_detail_in_the_body() -> None:
    """The one condition under which operator detail leaves the process:
    an administrator opened a time-boxed window on this credential."""
    app = _app("openai")

    @app.get("/fails-debugged")
    async def fails_debugged() -> None:
        request_context.grant_debug_detail(datetime.now(UTC) + timedelta(minutes=5))
        raise NoAvailableModelError(detail="operator-facing context")

    response = TestClient(app).get("/fails-debugged")
    assert response.json()["error"]["detail"] == "operator-facing context"


def test_an_expired_debug_window_reverts_to_the_normal_rule() -> None:
    """Time-boxed has to mean the box closes by itself: an expired window must
    behave exactly like no window, with nobody remembering to turn it off."""
    app = _app("openai")

    @app.get("/fails-expired")
    async def fails_expired() -> None:
        request_context.grant_debug_detail(datetime.now(UTC) - timedelta(minutes=5))
        raise NoAvailableModelError(detail="operator-facing context")

    body = TestClient(app).get("/fails-expired").json()
    assert "operator-facing context" not in str(body)


def test_the_gateway_renders_a_malformed_request_in_its_own_envelope() -> None:
    body = TestClient(_app("openai")).post("/validates", json={"minutes": "soon"}).json()

    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["request_id"].startswith("req_")
    # Pydantic's summary names the field and the rule. It describes the
    # caller's own request, so there is nothing here to withhold.
    assert "minutes" in body["error"]["message"]


def test_the_admin_entrances_render_one_in_theirs() -> None:
    """The flat shape, with the two keys every other admin error carries.

    Before this, `messageFor` in the frontend read `body.message` and then
    `body.detail` *if it were a string* — pydantic's is a list, so both fell
    through and the operator was shown "Request failed with status 422." in
    place of a message that had already named the field.
    """
    response = TestClient(_app("admin")).post("/validates", json={"minutes": "soon"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request"
    assert "minutes" in body["message"]
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_the_admin_document_advertises_the_422_it_actually_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The document and the handler are two places, and they drifted apart the
    moment the handler changed.

    FastAPI synthesises a 422 of its own `HTTPValidationError` for every route
    with a body, so adding the admin envelope silently made the OpenAPI
    document describe a shape the server no longer sends — and it was the
    generated frontend types, committed in the same change as the drift check
    itself, that carried the false description. Nothing could catch it: the
    contract file compares schemas against the document, and here the document
    was the wrong one.
    """
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    from app.infrastructure.main_admin_tailnet import create_app

    spec = create_app().openapi()
    bodies = {
        path: operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
        for path, methods in spec["paths"].items()
        for operation in methods.values()
        if "422" in operation.get("responses", {})
    }
    assert bodies, "no route advertises a 422; this test would pass vacuously"
    assert set(bodies.values()) == {"#/components/schemas/AdminErrorResponse"}

    declared = set(spec["components"]["schemas"]["AdminErrorResponse"]["properties"])
    sent = TestClient(_app("admin")).post("/validates", json={"minutes": "soon"}).json()
    assert set(sent) <= declared, (
        f"the handler sends keys the document omits: {set(sent) - declared}"
    )

    get_settings.cache_clear()
