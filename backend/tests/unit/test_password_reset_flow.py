from __future__ import annotations

import pytest

from app.domain.exceptions import (
    InvitationInvalidError,
)
from tests.unit.invitation_flow_fixtures import (
    ADMIN,
    Harness,
    _enrol,
)

pytest_plugins = ("tests.unit.invitation_flow_fixtures",)


async def test_consuming_a_reset_ends_every_session(harness: Harness) -> None:
    """The usual reason for a reset is that the old credential is in someone
    else's hands, so leaving their session alive would make it cosmetic."""
    issued = await _enrol(harness)
    reset = await harness.issue.issue_password_reset(ADMIN, user_id=issued.user.id)

    await harness.accept.consume_reset(reset.token, "another-strong-passphrase-9")

    assert harness.sessions.invalidated_all == [issued.user.id]


async def test_a_reset_leaves_the_second_factor_in_place(harness: Harness) -> None:
    """It replaces the password only. The next login still needs TOTP, which
    is why no second factor is demanded to consume the link."""
    issued = await _enrol(harness)
    before = harness.users.rows[issued.user.id].totp_secret
    reset = await harness.issue.issue_password_reset(ADMIN, user_id=issued.user.id)

    await harness.accept.consume_reset(reset.token, "another-strong-passphrase-9")

    assert harness.users.rows[issued.user.id].totp_secret == before


async def test_a_reset_link_is_single_use(harness: Harness) -> None:
    issued = await _enrol(harness)
    reset = await harness.issue.issue_password_reset(ADMIN, user_id=issued.user.id)

    await harness.accept.consume_reset(reset.token, "another-strong-passphrase-9")

    with pytest.raises(InvitationInvalidError):
        await harness.accept.consume_reset(reset.token, "yet-another-passphrase-11")
