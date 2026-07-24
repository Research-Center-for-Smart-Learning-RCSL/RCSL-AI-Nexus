"""Password strength, and the rules deliberately absent from it.

The threshold has to match frontend/src/features/auth/password-schema.ts. A
backend that is stricter produces a form which accepts a password the API then
refuses, with an error the user has no way to act on.
"""

from __future__ import annotations

import pytest

from app.adapters.crypto.zxcvbn_policy import MIN_LENGTH, ZxcvbnPasswordPolicy
from app.domain.exceptions import WeakPasswordError


@pytest.fixture
def policy() -> ZxcvbnPasswordPolicy:
    return ZxcvbnPasswordPolicy()


def test_a_long_unpredictable_passphrase_is_accepted(policy: ZxcvbnPasswordPolicy) -> None:
    policy.assert_acceptable("purple kettle lantern drift")


def test_anything_shorter_than_the_minimum_is_refused(policy: ZxcvbnPasswordPolicy) -> None:
    with pytest.raises(WeakPasswordError):
        policy.assert_acceptable("x" * (MIN_LENGTH - 1))


def test_a_password_satisfying_every_composition_rule_can_still_fail(
    policy: ZxcvbnPasswordPolicy,
) -> None:
    """The reason there are no composition rules. `Password123!` has upper,
    lower, digit and symbol, is twelve characters, and is guessed instantly."""
    with pytest.raises(WeakPasswordError):
        policy.assert_acceptable("Password123!")


def test_a_password_built_from_the_users_own_details_is_refused(
    policy: ZxcvbnPasswordPolicy,
) -> None:
    """Scoring without `user_inputs` would rate this as unrelated noise, when
    it is the first thing anyone targeting that person would try."""
    login = "jocelyn.tanaka@example.org"

    with pytest.raises(WeakPasswordError):
        policy.assert_acceptable("jocelyn.tanaka2026", user_inputs=[login, "Jocelyn Tanaka"])


def test_the_reason_is_returned_to_the_user(policy: ZxcvbnPasswordPolicy) -> None:
    """Unlike every other message in this flow, guidance here helps a
    legitimate user and tells an attacker nothing they could not learn by
    trying."""
    with pytest.raises(WeakPasswordError) as raised:
        policy.assert_acceptable("qwertyuiop12")

    assert raised.value.reason


def test_an_absurdly_long_password_is_not_handed_to_the_estimator(
    policy: ZxcvbnPasswordPolicy,
) -> None:
    """zxcvbn's matching is superlinear in length, and this runs on an
    unauthenticated endpoint. Past the ceiling it is length-checked only."""
    policy.assert_acceptable("a" * 5000)
