from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.entities.actor import Role
from app.domain.exceptions import (
    DebugWindowError,
    NotAuthorizedError,
    UserStateConflictError,
)
from app.domain.services.debug_window import MAX_DEBUG_WINDOW_MINUTES
from tests.unit.api_keys_and_users_fixtures import (
    ADMIN,
    MEMBER,
    NOW,
    KeyHarness,
    UserHarness,
    make_user,
)

pytest_plugins = ("tests.unit.api_keys_and_users_fixtures",)


async def test_opening_a_users_debug_window_stores_its_expiry_and_audits_it() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    user = await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    assert user.debug_logging_until == NOW + timedelta(minutes=60)
    assert harness.users.rows["u2"].debug_logging_until == NOW + timedelta(minutes=60)
    assert "user.debug_window_set" in harness.audit.actions()


async def test_zero_minutes_closes_a_users_debug_window() -> None:
    """Opening and closing are the same verb, so the audit log carries both."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    user = await harness.use_case.set_debug_window(ADMIN, "u2", minutes=0)

    assert user.debug_logging_until is None
    assert harness.users.rows["u2"].debug_logging_until is None


async def test_a_users_debug_window_cannot_exceed_the_shared_ceiling() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    with pytest.raises(DebugWindowError):
        await harness.use_case.set_debug_window(ADMIN, "u2", minutes=MAX_DEBUG_WINDOW_MINUTES + 1)

    assert harness.users.rows["u2"].debug_logging_until is None


async def test_a_keys_debug_window_cannot_exceed_the_shared_ceiling() -> None:
    """The same bound from the other side. It moved out of this use case into
    a shared rule, so it is asserted on both rather than trusted to stay."""
    harness = KeyHarness()
    issued = await harness.issue()

    with pytest.raises(DebugWindowError):
        await harness.use_case.set_debug_window(
            ADMIN, issued.key.key_id, minutes=MAX_DEBUG_WINDOW_MINUTES + 1
        )

    assert harness.keys.rows[issued.key.key_id].debug_logging_until is None


async def test_a_disabled_account_cannot_have_its_debug_window_opened() -> None:
    """The guard is the conditional UPDATE, not a check before it: a disable
    landing in between would otherwise leave the window open on an account
    nobody can sign in as, and report success."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    await harness.use_case.set_disabled(ADMIN, "u2", disabled=True)

    with pytest.raises(UserStateConflictError):
        await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    assert harness.users.rows["u2"].debug_logging_until is None
    assert "user.debug_window_set" not in harness.audit.actions()


async def test_setting_a_debug_window_needs_user_write() -> None:
    """It widens what the platform discloses about a *different* account, so
    it sits behind the same scope as editing one — not behind self-service."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.set_debug_window(MEMBER, "u2", minutes=60)

    assert harness.users.rows["u2"].debug_logging_until is None
