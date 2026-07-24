"""Changing a password and re-enrolling the second factor.

Both have a consequence that is easy to leave out and invisible when it is
missing: other sessions must die, and the old recovery codes must go.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
import pytest

from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.application.use_cases.manage_own_account import ManageOwnAccount
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.invitation import RecoveryCode
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
    NotAuthenticatedError,
    TotpEnrolmentExpiredError,
    WeakPasswordError,
)
from app.domain.services.token_service import TokenService
from app.shared.clock import FixedClock
from tests.unit.fakes import (
    AcceptingPolicy,
    FakeAudit,
    FakeHasher,
    FakeInvitations,
    FakeSecretBox,
    FakeSessions,
    FakeUsers,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105  (a test fixture)
CURRENT_PASSWORD = "the-current-passphrase-7"  # noqa: S105  (a test fixture)
NEW_PASSWORD = "a-different-passphrase-8"  # noqa: S105  (a test fixture)

ACTOR = Actor(
    id="u1",
    display="someone@example.org",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
)
SESSION_ID = "session-abc"


class Harness:
    def __init__(self, user: User) -> None:
        self.users = FakeUsers([user])
        self.invitations = FakeInvitations()
        self.sessions = FakeSessions()
        self.audit = FakeAudit()
        self.cache = InMemoryCache()
        secret_box = FakeSecretBox()

        self.accounts = ManageOwnAccount(
            users=self.users,
            invitations=self.invitations,
            tokens=TokenService(),
            totp=PyotpTotp(),
            hasher=FakeHasher(),
            policy=AcceptingPolicy(),
            secret_box=secret_box,
            pending=PendingEnrolment(self.cache, secret_box, ttl_seconds=600),
            sessions=self.sessions,
            audit=self.audit,
            clock=FixedClock(NOW),
            issuer="Test",
        )

    def pending_is_empty(self) -> bool:
        """No candidate secret was parked. A failed step-up must not leave one
        behind for a later confirm to pick up."""
        return self.cache._live(f"totp_enrol:{ACTOR.id}") is None


def make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": "u1",
        "login": "someone@example.org",
        "display_name": "Someone",
        "role": Role.USER,
        "password_hash": f"hashed:{CURRENT_PASSWORD}",
        "totp_secret": f"enc:{SECRET}",
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def harness() -> Harness:
    return Harness(make_user())


# --- password ------------------------------------------------------------


async def test_a_wrong_current_password_is_refused_and_audited(harness: Harness) -> None:
    with pytest.raises(InvalidCredentialsError):
        await harness.accounts.change_password(
            ACTOR,
            session_id=SESSION_ID,
            current_password="not it",  # noqa: S106  (a test fixture)
            new_password=NEW_PASSWORD,
        )

    assert ("user.password_verified", "u1", "denied") in harness.audit.entries


async def test_changing_a_password_ends_every_other_session(harness: Harness) -> None:
    """The usual reason for changing one is that the old value may be in
    someone else's hands. Leaving their session alive makes the change
    cosmetic."""
    await harness.accounts.change_password(
        ACTOR,
        session_id=SESSION_ID,
        current_password=CURRENT_PASSWORD,
        new_password=NEW_PASSWORD,
    )

    assert harness.sessions.invalidated_others == [("u1", SESSION_ID)]
    assert harness.users.rows["u1"].password_hash == f"hashed:{NEW_PASSWORD}"


async def test_setting_a_password_to_itself_is_refused(harness: Harness) -> None:
    """The strength estimator would accept a strong password being set to
    itself, and the caller would be told the change succeeded."""
    with pytest.raises(WeakPasswordError):
        await harness.accounts.change_password(
            ACTOR,
            session_id=SESSION_ID,
            current_password=CURRENT_PASSWORD,
            new_password=CURRENT_PASSWORD,
        )


async def test_a_session_outliving_its_account_is_refused() -> None:
    """401 rather than 404: the right client behaviour is to sign out."""
    harness = Harness(make_user(disabled_at=NOW))

    with pytest.raises(NotAuthenticatedError):
        await harness.accounts.change_password(
            ACTOR,
            session_id=SESSION_ID,
            current_password=CURRENT_PASSWORD,
            new_password=NEW_PASSWORD,
        )


# --- second factor -------------------------------------------------------


async def test_beginning_a_reenrolment_leaves_the_working_secret_alone(
    harness: Harness,
) -> None:
    """Opening the screen and closing it again must not break the
    authenticator someone is still using."""
    await harness.accounts.begin_totp_reenrolment(ACTOR, current_password=CURRENT_PASSWORD)

    assert harness.users.rows["u1"].totp_secret == f"enc:{SECRET}"


async def test_reenrolment_requires_the_current_password(harness: Harness) -> None:
    """Replacing the second factor is replacing a bearer credential. Without
    this a hijacked session could swap the authenticator and mint fresh
    recovery codes with no proof of the current one."""
    with pytest.raises(InvalidCredentialsError):
        await harness.accounts.begin_totp_reenrolment(ACTOR, current_password="wrong")  # noqa: S106

    assert harness.pending_is_empty()


async def test_confirming_swaps_the_secret_and_replaces_the_recovery_codes(
    harness: Harness,
) -> None:
    """Codes printed against the old secret must not survive. A recovery code
    bypasses the second factor outright, so leaving them redeemable would be a
    standing bypass of the factor just replaced."""
    await harness.invitations.save_recovery_codes(
        [RecoveryCode(id="old-1", user_id="u1", code_hash="stale")]
    )
    enrolment = await harness.accounts.begin_totp_reenrolment(
        ACTOR, current_password=CURRENT_PASSWORD
    )

    codes = await harness.accounts.confirm_totp_reenrolment(
        ACTOR, session_id=SESSION_ID, code=pyotp.TOTP(enrolment.secret).now()
    )

    assert len(codes) == 10
    assert "old-1" not in harness.invitations.codes
    assert harness.users.rows["u1"].totp_secret == f"enc:{enrolment.secret}"


async def test_confirming_without_beginning_is_refused(harness: Harness) -> None:
    with pytest.raises(TotpEnrolmentExpiredError):
        await harness.accounts.confirm_totp_reenrolment(ACTOR, session_id=SESSION_ID, code="123456")


async def test_reenrolment_also_ends_other_sessions(harness: Harness) -> None:
    enrolment = await harness.accounts.begin_totp_reenrolment(
        ACTOR, current_password=CURRENT_PASSWORD
    )

    await harness.accounts.confirm_totp_reenrolment(
        ACTOR, session_id=SESSION_ID, code=pyotp.TOTP(enrolment.secret).now()
    )

    assert harness.sessions.invalidated_others == [("u1", SESSION_ID)]
