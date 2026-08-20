from __future__ import annotations

from datetime import timedelta

import pytest

from app.adapters.persistence.repositories import PostgresRefusalRepository
from app.domain.entities.actor import Actor, Role
from app.domain.exceptions import (
    NotAuthorizedError,
)
from tests.unit.refusal_store_fixtures import (
    NOW,
    _actor,
    _refusal,
    _use_case,
)

pytest_plugins = ("tests.unit.refusal_store_fixtures",)


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
