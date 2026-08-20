from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.exceptions import (
    ContextTooLongError,
)
from app.infrastructure.config import get_settings
from tests.unit.error_precision_fixtures import (
    HEADERS,
    _admin,
    _app,
    _resolver_app,
    _too_long,
)

pytest_plugins = ("tests.unit.error_precision_fixtures",)


def test_neither_entrance_still_answers_with_fastapis_own_shape() -> None:
    """The defect stated directly: a bare `detail` list is what both used to
    return, and it is what a regression would look like."""
    for envelope in ("openai", "admin"):
        body = TestClient(_app(envelope)).post("/validates", json={"minutes": "soon"}).json()
        assert not isinstance(body.get("detail"), list), envelope


def test_an_open_window_on_the_user_row_reaches_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case the API-key window cannot cover: the management UI carries no
    API key, so an administrator debugging their own admin session is
    identified by this row and nothing else."""
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    user = _admin(debug_logging_until=datetime.now(UTC) + timedelta(minutes=30))
    body = TestClient(_resolver_app(user)).get("/fails-as-user", headers=HEADERS).json()

    # The admin envelope is the flat shape, which is the one an administrator
    # debugging the management UI actually receives.
    assert body["detail"] == "operator-facing context"
    get_settings.cache_clear()


def test_a_user_with_no_window_gets_the_normal_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same request against the same resolver, differing only in the
    column — so a resolver that granted unconditionally would fail here rather
    than pass both."""
    monkeypatch.setenv("AUTH_MODE", "tailnet")
    get_settings.cache_clear()

    body = TestClient(_resolver_app(_admin())).get("/fails-as-user", headers=HEADERS).json()

    assert "operator-facing context" not in str(body)
    get_settings.cache_clear()


def test_the_gateway_puts_the_figures_where_a_client_library_finds_them() -> None:
    """Flat inside `error`, beside `request_id`, which set the precedent for an
    extra key: OpenAI client libraries ignore what they do not recognise."""
    app = _app("openai")

    @app.get("/too-long")
    async def too_long() -> None:
        raise _too_long()

    error = TestClient(app).get("/too-long").json()["error"]

    assert error["estimated"] == 99429
    assert error["limit"] == 98304
    assert "60% of the whole" in error["composition"]


def test_the_admin_entrances_nest_them_where_that_envelope_puts_extras() -> None:
    """`InsufficientMemoryError`'s two numbers already go under `details`."""
    app = _app("admin")

    @app.get("/too-long")
    async def too_long() -> None:
        raise _too_long()

    body = TestClient(app).get("/too-long").json()

    assert body["details"]["limit"] == 98304


def test_the_figures_travel_in_the_message_too() -> None:
    """The fields are read only by code that knows to look for them, and the
    clients that most need this print `message` and nothing else."""
    assert "99,429" in _too_long().public_message
    assert "98,304" in _too_long().public_message


def test_a_refusal_without_figures_still_states_the_remedy() -> None:
    """The figures are optional; the remedy is not. Anything raising this
    without them must not degrade to a bare statement of fact."""
    message = ContextTooLongError().public_message

    assert "Retrying it unchanged cannot succeed" in message
    assert "99,429" not in message


def test_the_operator_detail_still_does_not_leave_the_process() -> None:
    """Widening what a 413 discloses must not widen `detail`, which is the
    channel the debug window exists to open deliberately."""
    app = _app("openai")

    @app.get("/too-long")
    async def too_long() -> None:
        raise _too_long()

    assert "operator-facing context" not in str(TestClient(app).get("/too-long").json())


def test_the_model_serving_the_request_is_still_not_named() -> None:
    """`limit` discloses roughly how large the model is; its identity is a
    separate question and the answer stayed no."""
    app = _app("openai")

    @app.get("/too-long")
    async def too_long() -> None:
        raise ContextTooLongError(
            detail="~9000 estimated tokens exceeds the 4096 qwen7b can read",
            estimated=9000,
            limit=4096,
            composition="~9000 in 3 messages",
        )

    assert "qwen7b" not in str(TestClient(app).get("/too-long").json())


def test_another_error_gains_no_such_fields() -> None:
    """The widening is scoped to the one error it was argued for."""
    body = TestClient(_app("openai")).get("/fails").json()

    assert "composition" not in body["error"]
