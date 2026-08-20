from __future__ import annotations

import pyotp
import pytest

from app.domain.entities.actor import Role
from app.domain.entities.invitation import RecoveryCode
from app.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTotpError,
    RateLimitedError,
    TotpRequiredError,
)
from app.domain.services.token_service import TokenService
from tests.unit.authenticate_local_fixtures import (
    IP,
    NOW,
    SECRET,
    RacingUsers,
    _exhaust_the_limiter,
    build,
    make_user,
)
from tests.unit.fakes import FakeInvitations, FakeUsers

pytest_plugins = ("tests.unit.authenticate_local_fixtures",)


async def test_every_password_failure_is_recorded_with_its_reason() -> None:
    """The response deliberately cannot distinguish these four; the log must.

    Recording only some of them would also be a timing oracle, since a
    database round trip is not free — which is the same property
    `dummy_verify` exists to protect.
    """
    cases = [
        (FakeUsers(), "nobody@example.org", "unknown_login"),
        (FakeUsers([make_user(disabled_at=NOW)]), "someone@example.org", "account_disabled"),
        (
            FakeUsers([make_user(password_hash=None, totp_secret=None)]),
            "someone@example.org",
            "no_local_credentials",
        ),
        (FakeUsers([make_user()]), "someone@example.org", "bad_password"),
    ]

    for users, login, expected in cases:
        use_case, _, audit = build(users)

        with pytest.raises(InvalidCredentialsError):
            await use_case.verify_password(login, "wrong", client_ip=IP)

        actor, _, _, outcome, detail = audit.only("user.sign_in_failed")
        assert detail["reason"] == expected
        assert detail["client_ip"] == IP
        assert outcome == "failed"
        # The presented login is recorded even when it matches no account: it
        # is what an investigator needs and it is not a secret.
        assert actor.display == login


async def test_a_failed_attempt_carries_no_privilege() -> None:
    """The audit subject is a label. If one ever reached a use case, the empty
    scope set is what must make that fail rather than succeed quietly."""
    use_case, _, audit = build(FakeUsers([make_user(role=Role.ADMIN)]))

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    actor, *_ = audit.only("user.sign_in_failed")
    assert actor.scopes == frozenset()


async def test_a_completed_sign_in_is_recorded_and_a_password_alone_is_not() -> None:
    """Two assertions in one test on purpose: the pair is the rule. A correct
    password produces a challenge, not a session, so it is not the event."""
    users = FakeUsers([make_user()])
    use_case, _, audit = build(users)

    await use_case.verify_password(
        "someone@example.org", "correct horse battery staple", client_ip=IP
    )
    assert audit.actions() == []

    await use_case.verify_totp("u1", pyotp.TOTP(SECRET).now(), client_ip=IP)

    _, _, target, outcome, detail = audit.only("user.signed_in")
    assert (target, outcome, detail["factor"]) == ("u1", "success", "totp")


async def test_losing_the_counter_race_is_distinguished_from_a_wrong_code() -> None:
    """Same 401 to the caller, different incident: this one means a second
    request presented the same code inside its window."""
    use_case, _, audit = build(RacingUsers([make_user()]))

    with pytest.raises(InvalidTotpError):
        await use_case.verify_totp("u1", pyotp.TOTP(SECRET).now(), client_ip=IP)

    _, _, _, _, detail = audit.only("user.sign_in_failed")
    assert detail["reason"] == "totp_replay"


async def test_a_sequential_replay_is_still_recorded_as_a_failure() -> None:
    """It arrives by the earlier path and is logged as a bad code, which is
    accurate: by then the counter has made it one."""
    use_case, _, audit = build(FakeUsers([make_user()]))
    current = pyotp.TOTP(SECRET).now()

    await use_case.verify_totp("u1", current, client_ip=IP)
    with pytest.raises(InvalidTotpError):
        await use_case.verify_totp("u1", current, client_ip=IP)

    assert audit.only("user.sign_in_failed")[4]["reason"] == "bad_totp_code"


async def test_spending_a_recovery_code_is_its_own_event() -> None:
    """Bypassing the second factor should be visible to someone scanning
    actions, not only to someone who thought to read inside `detail`."""
    tokens = TokenService()
    issued = tokens.issue_recovery_codes(count=1)

    invitations = FakeInvitations()
    await invitations.save_recovery_codes(
        [RecoveryCode(id="c0", user_id="u1", code_hash=issued[0].hashed)]
    )

    use_case, _, audit = build(FakeUsers([make_user()]), invitations)
    await use_case.verify_recovery_code("u1", issued[0].plaintext, client_ip=IP)

    assert audit.actions() == ["user.recovery_code_used", "user.signed_in"]
    assert audit.only("user.signed_in")[4]["factor"] == "recovery_code"


async def test_the_throttle_firing_is_itself_recorded() -> None:
    """The closest thing to the alerting section 5.3 promises. Before this the
    limiter's knowledge lived only in a Redis counter that expires."""
    use_case, _, audit = build(FakeUsers([make_user()]))
    await _exhaust_the_limiter(use_case)

    with pytest.raises(RateLimitedError):
        await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    _, _, _, outcome, detail = audit.only("user.sign_in_throttled")
    assert (outcome, detail["step"]) == ("denied", "password")


async def test_the_throttle_records_once_per_window_not_once_per_refusal() -> None:
    """A refused request costs the caller nothing — `assert_allowed` runs before
    the hash and the refused path never records a failure, so the counter stays
    above its ceiling for the whole window. A row per refusal would hand whoever
    is being refused an unauthenticated INSERT per request, into an append-only
    table kept for a year. `audit.only` is the assertion: it fails on two.
    """
    use_case, _, audit = build(FakeUsers([make_user()]))
    await _exhaust_the_limiter(use_case)

    for _ in range(20):
        with pytest.raises(RateLimitedError):
            await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    audit.only("user.sign_in_throttled")


async def test_a_throttled_attempt_on_a_real_account_is_attributed_to_it() -> None:
    """Attributed to `unknown` the row lands in the default tenant, and the
    logs read is tenant-scoped — so a tenant administrator watching an attack on
    their own user would see every failure and none of the rows saying the
    limiter had started refusing."""
    users = FakeUsers([make_user(tenant_id="t-research")])
    use_case, _, audit = build(users)
    await _exhaust_the_limiter(use_case)

    with pytest.raises(RateLimitedError):
        await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    actor, *_ = audit.only("user.sign_in_throttled")
    assert (actor.id, actor.tenant_id) == ("u1", "t-research")


async def test_an_account_disabled_inside_the_challenge_window_is_recorded() -> None:
    """The five-minute window between the two steps. `_assert_still_usable`
    already refused this; until the review of 2026-08-02 it refused silently,
    and it is exactly the event an incident review looks for."""
    users = FakeUsers([make_user(disabled_at=NOW)])
    use_case, _, audit = build(users)

    with pytest.raises(TotpRequiredError):
        await use_case.verify_totp("u1", pyotp.TOTP(SECRET).now(), client_ip=IP)

    assert audit.only("user.sign_in_failed")[4]["reason"] == "account_unusable"


async def test_a_login_that_is_not_address_shaped_is_not_stored_verbatim() -> None:
    """Logins are `EmailStr` at creation, so a string with no `@` is most often
    someone typing their password into the login field. Storing it verbatim
    would put a live credential in a table kept for a year and readable with
    `logs:read`."""
    use_case, _, audit = build(FakeUsers())

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password("hunter2-my-real-password", "wrong", client_ip=IP)

    actor, *_ = audit.only("user.sign_in_failed")
    assert "hunter2" not in actor.display
    assert actor.display.startswith("redacted:")


async def test_two_different_unknown_logins_stay_distinguishable() -> None:
    """The digest is what keeps the redaction useful: repeats of one string
    group, and a suspected value can be confirmed by hashing it."""
    use_case, _, audit = build(FakeUsers())

    for presented in ("one-bad-string", "another-bad-string", "one-bad-string"):
        with pytest.raises(InvalidCredentialsError):
            await use_case.verify_password(presented, "wrong", client_ip=IP)

    displays = [row[0].display for row in audit.rows]
    assert displays[0] == displays[2] != displays[1]


async def test_the_audit_row_lands_in_the_signing_in_user_s_tenant() -> None:
    """The logs screen is tenant-scoped. A row stamped with the default tenant
    is invisible to the only view its own tenant can read."""
    users = FakeUsers([make_user(tenant_id="t-research")])
    use_case, _, audit = build(users)

    with pytest.raises(InvalidCredentialsError):
        await use_case.verify_password("someone@example.org", "wrong", client_ip=IP)

    assert audit.only("user.sign_in_failed")[0].tenant_id == "t-research"
