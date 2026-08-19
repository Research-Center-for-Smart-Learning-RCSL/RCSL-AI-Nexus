"""Where a refused caller can read their own refusal back.

**The evening this exists for is 2026-08-17.** A `413` said only that the
conversation was too long — no size, no ceiling, no hint that a new conversation
would be refused identically — and the operator opened three of them. A `409` on
an API key's expiry said "The model is not in a state that allows this
operation", because the reason sat in `detail` and `detail` does not leave the
process; it was sent seven times in three minutes and read as the capability
edit beside it having failed. Both messages have since been fixed, and neither
fix helps the next error nobody has thought about.

What these pin is the part that generalises: a refusal is stored, it is stored
as what the caller was told rather than as what the operator would see, and the
person who provoked it can read it without an administrator opening a container
log.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.adapters.authz.role_authorization import ADMIN_ONLY_SCOPES, RoleAuthorization
from app.adapters.persistence.repositories import PostgresRefusalRepository
from app.application.use_cases.read_refusals import ReadRefusals
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.refusal import MAX_FIGURE_CHARS, Refusal
from app.domain.entities.retention import RETENTION_BOUNDS, RetentionDataset
from app.domain.exceptions import (
    ApiKeyLifetimeError,
    CapabilityNotIssuedError,
    ContextTooLongError,
    NotAuthorizedError,
    QuotaExceededError,
)
from app.infrastructure.db_roles import GATEWAY_DENIED_READ_TABLES, GATEWAY_WRITABLE_TABLES
from app.interfaces.http.errors import install_error_handlers, public_details
from app.interfaces.http.request_actor import remember_actor
from app.interfaces.http.request_context import RequestContextMiddleware
from tests.unit.fakes import FakeAudit

NOW = datetime(2026, 8, 18, 0, 30, tzinfo=UTC)
AUTHZ = RoleAuthorization()


def _actor(*, role: Role = Role.USER, actor_id: str = "u1", key: str | None = None) -> Actor:
    return Actor(
        id=actor_id,
        display=f"{actor_id}@example.test",
        role=role,
        source="local",
        scopes=AUTHZ.scopes_for(role.value),
        api_key_id=key,
    )


def _refusal(
    *,
    actor_id: str = "u1",
    actor_display: str = "someone@example.test",
    code: str = "context_too_long",
    at: datetime = NOW,
    figures: dict[str, object] | None = None,
) -> Refusal:
    return Refusal(
        id=f"{actor_id}-{code}-{at.isoformat()}",
        at=at,
        code=code,
        status=413,
        actor_id=actor_id,
        actor_display=actor_display,
        api_key_id=None,
        surface="gateway",
        method="POST",
        path="/v1/chat/completions",
        request_id="req_abc",
        message="This input is 140,059 tokens against a limit of 122,880.",
        figures=figures or {},
    )


class FakeRefusals:
    """Rows in memory, filtered the way the repository filters them."""

    def __init__(self, rows: list[Refusal] | None = None) -> None:
        self.rows = list(rows or [])

    def _match(self, row: Refusal, **f: object) -> bool:
        if f.get("actor_id") and row.actor_id != f["actor_id"]:
            return False
        display = f.get("actor_display")
        if isinstance(display, str) and display:
            # A substring, case-insensitively, which is what the repository's
            # `ILIKE '%needle%'` does. Matching exactly here would let a test
            # pass against a fake stricter than the thing it stands for.
            if display.casefold() not in row.actor_display.casefold():
                return False
        if f.get("api_key_id") and row.api_key_id != f["api_key_id"]:
            return False
        if f.get("code") and row.code != f["code"]:
            return False
        if f.get("request_id") and row.request_id != f["request_id"]:
            return False
        since, until = f.get("since"), f.get("until")
        if isinstance(since, datetime) and row.at < since:
            return False
        return not (isinstance(until, datetime) and row.at >= until)

    async def list_refusals(self, *, limit: int, offset: int, **f: object) -> list[Refusal]:
        matched = sorted(
            (r for r in self.rows if self._match(r, **f)), key=lambda r: r.at, reverse=True
        )
        return matched[offset : offset + limit]

    async def count_refusals(self, **f: object) -> int:
        return len([r for r in self.rows if self._match(r, **f)])


def _use_case(rows: list[Refusal]) -> tuple[ReadRefusals, FakeAudit]:
    trail = FakeAudit()
    return ReadRefusals(refusals=FakeRefusals(rows), authz=AUTHZ, audit=trail), trail


# --- who reads whose ------------------------------------------------------


async def test_a_caller_reads_their_own_without_an_administrator() -> None:
    """The whole feature. Before this, answering "why was I refused at 19:16?"
    meant somebody with shell access reading a container log."""
    use_case, _ = _use_case([_refusal(actor_id="u1"), _refusal(actor_id="u2")])

    page = await use_case.list_page(_actor(actor_id="u1"))

    assert [r.actor_id for r in page.entries] == ["u1"]
    assert page.scoped_to_self is True


async def test_asking_for_somebody_else_returns_your_own_rather_than_a_403() -> None:
    """Narrowed, not refused. Every account is expected to open this screen, so
    clearing a filter on it must not answer 403 — a page that 403s on its own
    default control reads as broken rather than as scoped."""
    use_case, _ = _use_case([_refusal(actor_id="u1"), _refusal(actor_id="u2")])

    page = await use_case.list_page(_actor(actor_id="u1"), actor_id="u2")

    assert [r.actor_id for r in page.entries] == ["u1"]


async def test_a_page_of_other_people_s_refusals_says_whose() -> None:
    """Without the name on the row this view is a column of uuids, and "whose
    413s are these?" — the question `refusal:read_all` exists to answer —
    becomes a lookup per row. Denormalised like `audit_log`'s, so it also
    survives the account being deleted, which is when somebody is most likely
    to be asking."""
    use_case, _ = _use_case(
        [
            _refusal(actor_id="u1", actor_display="teacher@example.test"),
            _refusal(actor_id="u2", actor_display="student@example.test"),
        ]
    )

    page = await use_case.list_page(_actor(role=Role.OPERATOR, actor_id="op"))

    assert {r.actor_display for r in page.entries} == {
        "teacher@example.test",
        "student@example.test",
    }


async def test_a_reader_may_narrow_to_one_account_when_they_may_see_all() -> None:
    """The port and the repository have filtered on `actor_id` from the start;
    what was missing is that the screen offered no way to set it, so an
    administrator looking at everyone's refusals could not look at one
    person's."""
    use_case, _ = _use_case([_refusal(actor_id="u1"), _refusal(actor_id="u2")])

    page = await use_case.list_page(_actor(role=Role.OPERATOR, actor_id="op"), actor_id="u2")

    assert [r.actor_id for r in page.entries] == ["u2"]


async def test_a_reader_may_narrow_by_the_name_the_screen_actually_shows() -> None:
    """The id filter was the only way to ask "whose?", and the id is a uuid.

    Nothing on the screen is a uuid a person could type: the name is resolved
    in the browser against the accounts the reader can list, and the row's own
    `actor_display` is the *credential's* — a login for somebody on an admin
    entrance, a key handle for a gateway caller. So an operator looking at a
    page of other people's refusals could see whose they were and could not ask
    for one person's without going and looking their uuid up somewhere else.

    A substring, because the two things worth searching by are a name somebody
    half-remembers and a key handle nobody memorises. And matched against the
    row rather than against the account table, which is what still finds the
    refusals of an account that has since been deleted — the case the
    denormalised column exists for, and the one where a join would return
    nothing at all.
    """
    use_case, _ = _use_case(
        [
            _refusal(actor_id="u1", actor_display="teacher@example.test"),
            _refusal(actor_id="u2", actor_display="student@example.test"),
        ]
    )

    page = await use_case.list_page(
        _actor(role=Role.OPERATOR, actor_id="op"), actor_display="TEACH"
    )

    assert [r.actor_id for r in page.entries] == ["u1"]
    assert page.total == 1


async def test_the_name_search_cannot_reach_past_the_narrowing() -> None:
    """The one thing this filter must not become: a second way in.

    A caller without `refusal:read_all` has the actor filter overwritten with
    their own id, and the name search is ANDed with it — so typing a
    colleague's name returns nothing rather than the colleague's refusals. An
    empty page is the correct answer here and the safe one: the filter can only
    ever subtract from what the reader was already allowed to see.
    """
    use_case, _ = _use_case(
        [
            _refusal(actor_id="u1", actor_display="teacher@example.test"),
            _refusal(actor_id="u2", actor_display="student@example.test"),
        ]
    )

    page = await use_case.list_page(_actor(actor_id="u1"), actor_display="student")

    assert page.entries == []
    assert page.total == 0


async def test_a_name_search_across_accounts_is_audited_and_says_what_was_searched() -> None:
    """A name reaches across accounts exactly as an id does, and names a set
    the searcher did not have to know the members of — "everyone called wu" is
    a broader reach than one uuid, not a narrower one. Recording only the id
    would leave the broader of the two reads as the unlogged one."""
    use_case, trail = _use_case([_refusal(actor_id="u2", actor_display="student@example.test")])

    await use_case.list_page(_actor(role=Role.OPERATOR, actor_id="op"), actor_display="student")

    assert [e[0] for e in trail.entries] == ["refusal.read_any"]
    assert trail.rows[0][4]["name"] == "student"


def test_the_name_search_spends_the_wildcards_it_is_given() -> None:
    """`%` and `_` mean something to `LIKE`, and a login is allowed to contain
    both. Unescaped, `a_b` finds `axb` — a filter that quietly returns more
    than it was asked for — and a bare `%` matches every row while looking on
    screen like a narrowing. The backslash goes first: escaping the escape
    character afterwards would escape the ones just added."""
    assert PostgresRefusalRepository._contains("a_b") == r"%a\_b%"
    assert PostgresRefusalRepository._contains("50%") == r"%50\%%"
    assert PostgresRefusalRepository._contains("a\\b") == r"%a\\b%"
    assert PostgresRefusalRepository._contains("teacher") == "%teacher%"


async def test_the_scope_that_made_that_evening_s_diagnosis_possible() -> None:
    use_case, _ = _use_case([_refusal(actor_id="u1"), _refusal(actor_id="u2")])

    page = await use_case.list_page(_actor(role=Role.OPERATOR, actor_id="op"))

    assert {r.actor_id for r in page.entries} == {"u1", "u2"}
    assert page.scoped_to_self is False


async def test_reading_across_accounts_is_audited_and_reading_your_own_is_not() -> None:
    """A month of somebody's 413s describes how they work, even though it holds
    nothing they typed. Reading your own is the feature working, and a row per
    screen refresh would be the noise `prompt_log.list` was denied for."""
    use_case, trail = _use_case([_refusal(actor_id="u1")])

    await use_case.list_page(_actor(actor_id="u1"))
    assert trail.entries == []

    await use_case.list_page(_actor(role=Role.OPERATOR, actor_id="op"), actor_id="u1")
    assert [e[0] for e in trail.entries] == ["refusal.read_any"]


async def test_an_administrator_reading_their_own_is_not_an_audited_event() -> None:
    """The audit row records reaching across accounts. An administrator looking
    at their own refusals is doing what every account may do."""
    use_case, trail = _use_case([_refusal(actor_id="admin")])

    await use_case.list_page(_actor(role=Role.ADMIN, actor_id="admin"), actor_id="admin")

    assert trail.entries == []


async def test_an_account_with_no_scope_at_all_is_refused() -> None:
    stripped = Actor(id="u1", display="u1", role=Role.USER, source="local", scopes=frozenset())
    use_case, _ = _use_case([])

    with pytest.raises(NotAuthorizedError):
        await use_case.list_page(stripped)


async def test_the_page_is_bounded_however_large_a_limit_is_asked_for() -> None:
    use_case, _ = _use_case([_refusal(at=NOW - timedelta(minutes=i)) for i in range(30)])

    page = await use_case.list_page(_actor(), limit=10_000)

    assert page.limit == 200
    assert page.total == 30


async def test_the_filters_the_screen_offers_reach_the_repository() -> None:
    """`since`/`until` were plumbed through the prompt-log port and the query
    while no caller could set either, so two comparisons were unreachable and
    read as a working filter to anyone looking at the SQL."""
    rows = [
        _refusal(code="context_too_long", at=NOW),
        _refusal(code="quota_exceeded", at=NOW - timedelta(days=2)),
    ]
    use_case, _ = _use_case(rows)

    by_code = await use_case.list_page(_actor(), code="quota_exceeded")
    by_time = await use_case.list_page(_actor(), since=NOW - timedelta(hours=1))

    assert [r.code for r in by_code.entries] == ["quota_exceeded"]
    assert [r.code for r in by_time.entries] == ["context_too_long"]


# --- what is stored -------------------------------------------------------


def test_the_stored_figures_are_the_ones_the_caller_was_sent() -> None:
    """One function builds both, which is the only way "a row is a copy of your
    own answer" stays true when somebody adds a tenth error that carries one."""
    exc = ContextTooLongError(
        detail="operator-facing, and it stays in this process",
        estimated=140_059,
        limit=122_880,
        composition="~17189 in 4 messages, ~0 in prior tool calls, ~122870 in 286 definitions",
        basis="tokenizer",
    )

    figures = public_details(exc)

    assert figures["estimated"] == 140_059
    assert figures["limit"] == 122_880
    assert figures["basis"] == "tokenizer"
    assert "operator-facing" not in str(figures)


def test_a_wait_a_caller_was_told_to_serve_is_kept_as_a_figure() -> None:
    """It arrives as a header, and a caller reading their refusals a day later
    has no headers. "How long was I told to wait" is the question a 429 in that
    list raises."""
    figures = public_details(QuotaExceededError(retry_after_seconds=3600))

    assert figures["retry_after_seconds"] == 3600


def test_the_figure_that_cost_an_operator_an_evening_is_now_stored() -> None:
    """The 409 whose reason sat in `detail`. `ApiKeyLifetimeError` carries the
    number now, and the store keeps whatever the caller was shown."""
    figures = public_details(ApiKeyLifetimeError(maximum_days=365))

    assert figures == {"maximum_days": 365}


def test_an_over_long_figure_is_cut_and_says_so_rather_than_being_lost() -> None:
    """`audit_log` lost whole rows to a value wider than its column, silently,
    so padding a URL suppressed the record of probing it."""
    long_composition = "x" * (MAX_FIGURE_CHARS + 500)

    cut = _refusal(figures={"composition": long_composition}).truncated()

    assert cut.figures["composition"].endswith("(truncated)")
    assert len(cut.figures["composition"]) < len(long_composition)


def test_a_row_with_no_figures_is_left_alone() -> None:
    refusal = _refusal()
    assert refusal.truncated() is refusal


# --- the write point ------------------------------------------------------


class RecordingWriter:
    def __init__(self) -> None:
        self.rows: list[Refusal] = []

    async def record(self, refusal: Refusal) -> None:
        self.rows.append(refusal)


def _app(*, identify: Actor | None) -> tuple[FastAPI, RecordingWriter]:
    app = FastAPI()
    writer = RecordingWriter()
    install_error_handlers(app, envelope="openai", surface="gateway")
    app.add_middleware(RequestContextMiddleware)
    app.state.refusals = writer

    @app.get("/v1/models/{model_id}")
    async def refuses(model_id: str, request: Request) -> None:
        if identify is not None:
            remember_actor(request, identify)
        raise ContextTooLongError(
            detail="operator-facing", estimated=140_059, limit=122_880, basis="tokenizer"
        )

    @app.get("/v1/explodes")
    async def explodes(request: Request) -> None:
        if identify is not None:
            remember_actor(request, identify)
        raise RuntimeError("a wiring mistake")

    return app, writer


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


# --- the boundaries around the table --------------------------------------


def test_the_gateway_may_write_this_table_and_may_not_read_it() -> None:
    """It holds no request content, so a gateway reading it would not be reading
    anybody's ideas — it would be reading every tenant's refusal history from
    the one process exposed to the internet. It writes a row and has no use for
    any row."""
    assert "refusals" in GATEWAY_WRITABLE_TABLES
    assert "refusals" in GATEWAY_DENIED_READ_TABLES


def test_the_dataset_is_bounded_by_a_ceiling_as_well_as_a_floor() -> None:
    """A ceiling because a year of somebody's 413s is a description of how they
    work that nobody asked to have kept; a floor because the person who reads
    this table is the person who was refused, and a Friday refusal has to
    survive until Monday."""
    bounds = RETENTION_BOUNDS[RetentionDataset.REFUSALS]

    assert bounds.maximum_days is not None
    assert bounds.minimum_days >= 7
    assert bounds.minimum_days <= bounds.default_days <= bounds.maximum_days


def test_reading_your_own_refusals_is_not_an_administrative_privilege() -> None:
    """Two people lost an evening each to refusals they could not look up. A
    scope only an administrator holds would have left them exactly there."""
    assert Scope.REFUSAL_READ_OWN in AUTHZ.scopes_for("user")
    assert Scope.REFUSAL_READ_ALL not in AUTHZ.scopes_for("user")
    assert Scope.REFUSAL_READ_ALL in AUTHZ.scopes_for("operator")


def test_who_sees_whose_refusals_is_exactly_who_sees_whose_usage() -> None:
    """Pinned as a whole table, because "which roles" is the question this
    feature is most likely to be asked and least likely to be re-derived.

    The rule is not a new judgement: both datasets are metadata about requests
    rather than their content, and the roles that investigate load are the
    roles that investigate refusals. Stating it as an equality means a future
    change to one has to be a deliberate change to the other, or this fails.

    **`service` is the one deliberate difference, and it is a difference in
    kind.** An API key may read its own usage, and it may not read its own
    refusals — not because the holder should not see them, but because there is
    nowhere for that read to happen: the gateway mounts no route here and its
    database account has `SELECT` on this table revoked, following
    `prompt_logs`. A scope granted here would promise something no endpoint
    serves. The key's owner is an account, and they read their own refusals on
    the admin entrance like everybody else.
    """
    for role in Role:
        if role is Role.SERVICE:
            continue
        scopes = AUTHZ.scopes_for(role.value)
        assert (Scope.REFUSAL_READ_OWN in scopes) == (Scope.USAGE_READ_OWN in scopes), role
        assert (Scope.REFUSAL_READ_ALL in scopes) == (Scope.USAGE_READ_ALL in scopes), role

    service = AUTHZ.scopes_for(Role.SERVICE.value)
    assert Scope.REFUSAL_READ_OWN not in service
    assert Scope.REFUSAL_READ_ALL not in service

    assert Scope.REFUSAL_READ_ALL not in ADMIN_ONLY_SCOPES, (
        "deliberately not beside prompt_log:read — that one reads what somebody "
        "typed, and this one reads only what the platform told them"
    )


# --- the resolver that forgot -------------------------------------------


def test_every_identity_dependency_leaves_its_actor_on_the_request() -> None:
    """The defect a deployment found and no test would have.

    `actor_from_request` is how the exception handler says *who* was refused
    after the frame that identified them is gone, and its module docstring says
    each resolver leaves a copy there on its way past. The API-key resolver did
    not — and while its only consumer was `_audit_refusal`, which returns early
    on the gateway because that application has no `audit` on its state, the
    omission was unobservable. It became observable the moment refusals were
    stored: a deployed `413` on a real key, the exact refusal this table was
    built for, was answered correctly and written nowhere.

    Checked over the source rather than by exercising each dependency, because
    what makes this stick is that a *fourth* one added later cannot forget
    either — a test that drove the four that exist would pass on the day the
    fifth arrives.

    The rule is over the public functions returning `Actor`, which are exactly
    what a router may `Depends` on, and it follows calls within the package so
    a dependency may delegate: `authenticate_api_key` remembers by way of
    `_authenticate`, and the two identity resolvers by wrapping `_actor_for` in
    the call itself.
    """
    root = Path(__file__).resolve().parents[2] / "app" / "interfaces" / "http" / "middleware"
    definitions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}
    returns_actor: set[str] = set()
    for module in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                definitions[node.name] = node
                if getattr(node.returns, "id", None) == "Actor":
                    returns_actor.add(node.name)

    def calls(name: str) -> set[str]:
        return {
            call.func.id
            for call in ast.walk(definitions[name])
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }

    remembers = {name for name in definitions if "remember_actor" in calls(name)}
    changed = True
    while changed:
        changed = False
        for name in definitions:
            if name not in remembers and calls(name) & remembers:
                remembers.add(name)
                changed = True

    dependencies = {name for name in returns_actor if not name.startswith("_")}
    assert len(dependencies) >= 3, f"expected the tailnet, session and API-key ones: {dependencies}"

    forgot = sorted(dependencies - remembers)
    assert forgot == [], f"identity dependencies that never remember their actor: {forgot}"


def test_the_api_key_resolver_remembers_before_the_checks_that_refuse() -> None:
    """Remembering at the `return` stored the 413s and dropped everything the
    checks above it raise: a rate limit, an exhausted quota, a blocked country,
    a source outside the key's allowlist. All four refuse a caller who is
    already fully identified — and a `429` nobody can look up is exactly the
    row `retry_after_seconds` was added for, since the header carrying it is
    gone by the time anybody reads back.

    Pinned as an ordering over the source, because that is what the defect was.
    """
    module = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "interfaces"
        / "http"
        / "middleware"
        / "api_key_auth"
        / "authentication.py"
    )
    tree = ast.parse(module.read_text())
    resolver = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_authenticate"
    )

    def line_of(name: str) -> int:
        return min(
            (
                call.lineno
                for call in ast.walk(resolver)
                if isinstance(call, ast.Call) and name in ast.dump(call.func)
            ),
            default=-1,
        )

    remembered = line_of("remember_actor")
    assert remembered > 0
    for check in (
        "assert_allowed",
        "_assert_source_allowed",
        "_assert_within_rate_limit",
        "_assert_within_quota",
    ):
        refuses_at = line_of(check)
        assert refuses_at > 0, f"{check} is no longer in this resolver"
        assert remembered < refuses_at, (
            f"{check} can refuse an identified caller before the request remembers who they are, "
            "so its refusal is stored nowhere"
        )
