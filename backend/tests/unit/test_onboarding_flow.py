from __future__ import annotations

from datetime import timedelta

import pyotp
import pytest

from app.domain.entities.actor import Role
from app.domain.exceptions import (
    InvalidTotpError,
    InvitationInvalidError,
    NotAuthorizedError,
    TotpEnrolmentExpiredError,
    UserAlreadyExistsError,
)
from tests.unit.invitation_flow_fixtures import (
    ADMIN,
    PLAIN_USER,
    STRONG_PASSWORD,
    Harness,
    _enrol,
)

pytest_plugins = ("tests.unit.invitation_flow_fixtures",)


async def test_creating_an_account_returns_the_link_exactly_once(harness: Harness) -> None:
    issued = await harness.issue.create_account(
        ADMIN, login="New@Example.org", display_name="New", role=Role.USER
    )

    assert issued.token
    stored = harness.invitations.rows[issued.invitation_id]
    # Only the hash is retained; the plaintext is unrecoverable afterwards.
    assert stored.token_hash == harness.tokens.hash_token(issued.token)
    assert issued.token not in stored.token_hash

    # Logins are normalised, so `New@Example.org` and `new@example.org` cannot
    # become two accounts.
    assert issued.user.login == "new@example.org"


async def test_a_new_account_has_no_credentials(harness: Harness) -> None:
    """The platform never transmits one. Anything else would mean a temporary
    password state that people forget to leave."""
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )

    assert issued.user.password_hash is None
    assert issued.user.totp_secret is None
    assert not issued.user.can_use_public_entrance


async def test_a_non_admin_cannot_invite(harness: Harness) -> None:
    with pytest.raises(NotAuthorizedError):
        await harness.issue.create_account(
            PLAIN_USER, login="new@example.org", display_name="New", role=Role.ADMIN
        )


async def test_a_duplicate_login_is_refused(harness: Harness) -> None:
    await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )

    with pytest.raises(UserAlreadyExistsError):
        await harness.issue.create_account(
            ADMIN, login="new@example.org", display_name="Again", role=Role.USER
        )


async def test_issuing_a_new_link_kills_the_previous_one(harness: Harness) -> None:
    """Otherwise a link that was intercepted stays usable after the real
    recipient asks for another."""
    first = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    second = await harness.issue.reissue_onboarding(ADMIN, user_id=first.user.id)

    with pytest.raises(InvitationInvalidError):
        await harness.accept.begin(first.token)

    assert (await harness.accept.begin(second.token)).login == "new@example.org"


async def test_an_enrolled_account_cannot_be_handed_a_new_onboarding_link(
    harness: Harness,
) -> None:
    """That would let an administrator silently replace a working second
    factor. A password reset is the supported remedy."""
    issued = await _enrol(harness)

    with pytest.raises(UserAlreadyExistsError):
        await harness.issue.reissue_onboarding(ADMIN, user_id=issued.user.id)


async def test_accepting_sets_both_credentials_together(harness: Harness) -> None:
    issued = await _enrol(harness)

    user = harness.users.rows[issued.user.id]
    assert user.password_hash is not None
    assert user.totp_secret is not None
    assert user.can_use_public_entrance


async def test_accepting_returns_ten_recovery_codes(harness: Harness) -> None:
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    enrolment = await harness.accept.begin(issued.token)
    codes = await harness.accept.complete(
        issued.token, STRONG_PASSWORD, pyotp.TOTP(enrolment.secret).now()
    )

    assert len(codes) == 10
    assert len(set(codes)) == 10


async def test_a_link_cannot_be_used_twice(harness: Harness) -> None:
    issued = await _enrol(harness)

    with pytest.raises(InvitationInvalidError):
        await harness.accept.begin(issued.token)


async def test_a_wrong_code_does_not_burn_the_link(harness: Harness) -> None:
    """Everything the caller can get wrong is checked before the single-use
    claim, so a mistyped code costs a retry rather than a reissue."""
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    enrolment = await harness.accept.begin(issued.token)

    with pytest.raises(InvalidTotpError):
        await harness.accept.complete(issued.token, STRONG_PASSWORD, "000000")

    codes = await harness.accept.complete(
        issued.token, STRONG_PASSWORD, pyotp.TOTP(enrolment.secret).now()
    )
    assert codes


async def test_beginning_twice_shows_the_same_secret(harness: Harness) -> None:
    """A page refresh must not invalidate the QR the recipient just scanned."""
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )

    first = await harness.accept.begin(issued.token)
    second = await harness.accept.begin(issued.token)

    assert first.secret == second.secret


async def test_completing_without_beginning_is_refused(harness: Harness) -> None:
    """The pending secret is what proves an authenticator was configured. If
    it has expired the recipient re-scans; there is no path that sets a
    password without one."""
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )

    with pytest.raises(TotpEnrolmentExpiredError):
        await harness.accept.complete(issued.token, STRONG_PASSWORD, "123456")


async def test_an_expired_link_is_refused(harness: Harness) -> None:
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    harness.clock.advance(timedelta(hours=73).total_seconds())

    with pytest.raises(InvitationInvalidError):
        await harness.accept.begin(issued.token)


async def test_a_reset_link_is_refused_by_the_onboarding_endpoint(harness: Harness) -> None:
    """Unknown, expired, consumed and wrong-purpose all raise the same error,
    so the endpoint cannot be used to learn which links exist."""
    issued = await _enrol(harness)
    reset = await harness.issue.issue_password_reset(ADMIN, user_id=issued.user.id)

    with pytest.raises(InvitationInvalidError):
        await harness.accept.begin(reset.token)
