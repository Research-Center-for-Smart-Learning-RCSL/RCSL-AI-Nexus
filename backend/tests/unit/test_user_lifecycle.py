from __future__ import annotations

import pytest

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import (
    LastAdministratorError,
    NotAuthorizedError,
    UserNotFoundError,
)
from tests.unit.api_keys_and_users_fixtures import (
    ADMIN,
    NOW,
    UserHarness,
    _key_for,
    make_user,
)

pytest_plugins = ("tests.unit.api_keys_and_users_fixtures",)


async def test_the_last_administrator_cannot_be_deleted() -> None:
    """Removing them leaves an instance nobody can manage, and the bootstrap
    setting does not come back: it is inert once any user row exists."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    other_admin = Actor(
        id="u2", display="u2", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
    )

    with pytest.raises(LastAdministratorError):
        await harness.use_case.delete(other_admin, "admin-1")


async def test_the_last_administrator_cannot_be_demoted() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    other_admin = Actor(
        id="u2", display="u2", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
    )

    with pytest.raises(LastAdministratorError):
        await harness.use_case.update(other_admin, "admin-1", role=Role.USER)


async def test_an_administrator_cannot_delete_themselves() -> None:
    """The frontend had this check and it never fired, because it compared a
    UUID against a login."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("a2", Role.ADMIN)])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.delete(ADMIN, "admin-1")


async def test_an_administrator_cannot_demote_themselves() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("a2", Role.ADMIN)])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.update(ADMIN, "admin-1", role=Role.USER)


async def test_changing_a_role_ends_that_users_sessions() -> None:
    """Scopes are derived from the role at request time, so a live session
    would otherwise keep what it was granted at login until it expired."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.update(ADMIN, "u2", role=Role.ADMIN)

    assert harness.sessions.invalidated_all == ["u2"]


async def test_renaming_does_not_end_sessions() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.update(ADMIN, "u2", display_name="Renamed")

    assert harness.sessions.invalidated_all == []


async def test_disabling_ends_sessions_immediately() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.set_disabled(ADMIN, "u2", disabled=True)

    assert harness.sessions.invalidated_all == ["u2"]
    assert harness.users.rows["u2"].disabled_at == NOW


async def test_deleting_a_user_removes_the_rows_that_reference_them() -> None:
    """`api_keys`, `invitations` and `recovery_codes` carry a foreign key, so
    they go first or the delete is impossible. Their keys stopping is the
    correct consequence."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    harness.keys.rows["k1"] = _key_for("u2")

    await harness.use_case.delete(ADMIN, "u2")

    assert "u2" not in harness.users.rows
    assert harness.keys.rows == {}
    assert "user.deleted" in harness.audit.actions()


async def test_deleting_an_unknown_user_is_a_404() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN)])

    with pytest.raises(UserNotFoundError):
        await harness.use_case.delete(ADMIN, "nobody")
