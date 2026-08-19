from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.domain.exceptions import (
    CapabilityNotIssuedError,
    NotAuthorizedError,
)
from app.infrastructure.db_roles import GATEWAY_DENIED_READ_TABLES, GATEWAY_WRITABLE_TABLES
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.request_actor import remember_actor
from app.interfaces.http.request_context import RequestContextMiddleware
from tests.unit.refusal_store_fixtures import (
    RecordingWriter,
    _actor,
    _app,
)

pytest_plugins = ("tests.unit.refusal_store_fixtures",)


def test_a_refusal_is_stored_from_the_one_place_every_refusal_passes_through() -> None:
    """Not the inference path's `finally`, which was the shape this was
    specified in: the 409 that cost an operator an evening was an API key's
    expiry on the admin surface and never reaches `RouteChatRequest`."""
    app, writer = _app(identify=_actor(key="k1"))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/models/abc")

    assert response.status_code == 413
    assert len(writer.rows) == 1
    stored = writer.rows[0]
    assert stored.code == "context_too_long"
    assert stored.status == 413
    assert stored.api_key_id == "k1"
    assert stored.request_id == response.json()["error"]["request_id"]


def test_the_stored_row_carries_the_route_and_not_the_caller_s_own_path() -> None:
    """`/v1/models/{model_id}`, so a thousand refusals on one endpoint group
    instead of scattering by id — and so nothing a caller put in a path
    parameter is stored."""
    app, writer = _app(identify=_actor())

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/v1/models/secret-alias")

    assert writer.rows[0].path == "/v1/models/{model_id}"
    assert "secret-alias" not in writer.rows[0].path


def test_a_path_value_that_collides_with_an_earlier_segment_is_not_substituted() -> None:
    """Substituting the parameter *values* into the path looked like it worked.

    The values are the caller's, so one that also appears earlier templates the
    wrong segment: `GET /admin/users/admin` with `user_id="admin"` stored itself
    as `/{user_id}/users/admin`, and a key called `keys` turned
    `/admin/api-keys/keys` into `/admin/api-{key_id}/keys`. Any caller could
    provoke a row naming neither the route nor their request. The prefix comes
    from the request and the tail from the route template, by position.
    """
    app = FastAPI()
    writer = RecordingWriter()
    install_error_handlers(app, envelope="admin", surface="admin-tailnet")
    app.add_middleware(RequestContextMiddleware)
    app.state.refusals = writer

    @app.get("/admin/users/{user_id}")
    async def refuses(user_id: str, request: Request) -> None:
        remember_actor(request, _actor())
        raise NotAuthorizedError(detail="operator-facing")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/admin/users/admin")

    assert writer.rows[0].path == "/admin/users/{user_id}"


def test_the_operator_facing_detail_does_not_reach_the_row() -> None:
    """The rule three other places in this codebase turn on. A row a caller may
    read must not contain what only an operator may."""
    app, writer = _app(identify=_actor())

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/v1/models/abc")

    assert "operator-facing" not in writer.rows[0].message
    assert "operator-facing" not in str(writer.rows[0].figures)


def test_a_five_hundred_is_stored_too_because_it_is_the_worst_of_them() -> None:
    """A caller holding a request id and an apology has exactly the problem this
    table was built for. The traceback stays in the log."""
    app, writer = _app(identify=_actor())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/explodes")

    assert response.status_code == 500
    assert [(r.code, r.status) for r in writer.rows] == [("internal_error", 500)]
    assert writer.rows[0].figures == {}


def test_an_unidentified_caller_leaves_no_row() -> None:
    """No reader owns it, and it would be written at whatever rate an
    anonymous client chooses. The identity-plane refusals that matter are in
    `audit_log` already, by §12."""
    app, writer = _app(identify=None)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/v1/models/abc")

    assert writer.rows == []


def test_a_deployment_without_a_writer_still_answers_its_callers() -> None:
    """The migration may not have run. A refusal that cannot be stored is still
    a refusal the caller is owed."""
    app, _ = _app(identify=_actor())
    del app.state.refusals

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/models/abc")

    assert response.status_code == 413


def test_the_body_and_the_row_carry_the_same_figures_on_the_gateway() -> None:
    """`public_details` claims to be the one function both readers use, and it
    was not: the OpenAI envelope still called `_context_fields`, so a stored row
    could carry a figure the response had not. "A row is a copy of the answer
    you already had" is the whole of why this table is safe to show its own
    subject."""
    app = FastAPI()
    writer = RecordingWriter()
    install_error_handlers(app, envelope="openai", surface="gateway")
    app.add_middleware(RequestContextMiddleware)
    app.state.refusals = writer

    @app.get("/v1/chat/completions")
    async def refuses(request: Request) -> None:
        remember_actor(request, _actor(key="k1"))
        raise CapabilityNotIssuedError(capability="code", available=["chat"])

    with TestClient(app, raise_server_exceptions=False) as client:
        error = client.get("/v1/chat/completions").json()["error"]

    stored = writer.rows[0].figures
    assert error["capability"] == "code"
    assert error["available"] == ["chat"]
    assert {key: error[key] for key in stored} == stored


def test_the_gateway_may_write_this_table_and_may_not_read_it() -> None:
    """It holds no request content, so a gateway reading it would not be reading
    anybody's ideas — it would be reading every tenant's refusal history from
    the one process exposed to the internet. It writes a row and has no use for
    any row."""
    assert "refusals" in GATEWAY_WRITABLE_TABLES
    assert "refusals" in GATEWAY_DENIED_READ_TABLES
