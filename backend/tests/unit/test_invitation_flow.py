"""Issuing and redeeming links, and the first-admin bootstrap.

The cases worth pinning are the ones where a correct-looking implementation
still fails: a link that survives its use, a mistyped code that burns the
link anyway, an account that ends up with a password but no second factor,
and a bootstrap that fires twice because a page load made several requests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.application.use_cases.accept_invitation import AcceptInvitation
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import (
    InvalidTotpError,
    InvitationInvalidError,
    NotAuthorizedError,
    TotpEnrolmentExpiredError,
    UserAlreadyExistsError,
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

ADMIN = Actor(
    id="admin-1",
    display="admin@example.org",
    role=Role.ADMIN,
    source="tailnet",
    scopes=frozenset(Scope),
)
PLAIN_USER = Actor(
    id="u2",
    display="user@example.org",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
)

STRONG_PASSWORD = "purple-kettle-lantern-33"  # noqa: S105  (a test fixture)


class Harness:
    def __init__(self) -> None:
        self.users = FakeUsers()
        self.invitations = FakeInvitations()
        self.audit = FakeAudit()
        self.sessions = FakeSessions()
        self.clock = FixedClock(NOW)
        self.tokens = TokenService()
        self.cache = InMemoryCache()
        self.secret_box = FakeSecretBox()

        self.issue = IssueInvitation(
            users=self.users,
            invitations=self.invitations,
            tokens=self.tokens,
            audit=self.audit,
            authz=RoleAuthorization(),
            clock=self.clock,
            ttl_seconds=72 * 3600,
        )
        self.accept = AcceptInvitation(
            users=self.users,
            invitations=self.invitations,
            tokens=self.tokens,
            totp=PyotpTotp(),
            hasher=FakeHasher(),
            policy=AcceptingPolicy(),
            secret_box=self.secret_box,
            pending=PendingEnrolment(self.cache, self.secret_box, ttl_seconds=600),
            sessions=self.sessions,
            audit=self.audit,
            clock=self.clock,
            issuer="Test",
        )


@pytest.fixture
def harness() -> Harness:
    return Harness()


# --- issuing -------------------------------------------------------------


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


# --- accepting -----------------------------------------------------------


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


# --- reset ---------------------------------------------------------------


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


# --- bootstrap -----------------------------------------------------------


async def test_bootstrap_creates_one_admin_and_then_goes_inert() -> None:
    users = FakeUsers()
    bootstrap = BootstrapFirstAdmin(
        users=users,
        audit=FakeAudit(),
        authz=RoleAuthorization(),
        bootstrap_login="Founder@Example.org",
    )

    created = await bootstrap.claim("founder@example.org", "Founder")
    assert created is not None
    assert created.role is Role.ADMIN

    # Inert once any user exists, so the setting does not need removing.
    assert await bootstrap.claim("founder@example.org", "Founder") is None


async def test_bootstrap_ignores_any_other_login() -> None:
    users = FakeUsers()
    bootstrap = BootstrapFirstAdmin(
        users=users,
        audit=FakeAudit(),
        authz=RoleAuthorization(),
        bootstrap_login="founder@example.org",
    )

    assert await bootstrap.claim("someone.else@example.org", "Else") is None
    assert users.rows == {}


async def test_bootstrap_is_off_when_unset() -> None:
    """An empty setting must not mean "the first caller wins"."""
    bootstrap = BootstrapFirstAdmin(
        users=FakeUsers(),
        audit=FakeAudit(),
        authz=RoleAuthorization(),
        bootstrap_login="",
    )

    assert await bootstrap.claim("anyone@example.org", "Anyone") is None


async def test_concurrent_first_requests_produce_one_account() -> None:
    """A browser's first page load fires several requests, all of which read
    the table before any of them has written to it. The `count() == 0` guard
    therefore passes for every one, and only the atomic claim keeps them from
    all inserting: the losers would otherwise violate the unique constraint at
    commit and surface as a 500 on a fresh deployment.
    """

    class AlwaysEmpty(FakeUsers):
        async def count(self) -> int:
            return 0

    users = AlwaysEmpty()
    bootstrap = BootstrapFirstAdmin(
        users=users,
        audit=FakeAudit(),
        authz=RoleAuthorization(),
        bootstrap_login="founder@example.org",
    )

    first = await bootstrap.claim("founder@example.org", "Founder")
    second = await bootstrap.claim("founder@example.org", "Founder")

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(users.rows) == 1


async def test_the_bootstrap_admin_has_no_local_credentials() -> None:
    """The tailnet entrance does not use them. If that person later needs the
    public entrance they issue themselves an invitation."""
    bootstrap = BootstrapFirstAdmin(
        users=FakeUsers(),
        audit=FakeAudit(),
        authz=RoleAuthorization(),
        bootstrap_login="founder@example.org",
    )

    created = await bootstrap.claim("founder@example.org", "Founder")

    assert created is not None
    assert created.password_hash is None
    assert created.totp_secret is None


# --- helpers -------------------------------------------------------------


async def _enrol(harness: Harness):
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    enrolment = await harness.accept.begin(issued.token)
    await harness.accept.complete(issued.token, STRONG_PASSWORD, pyotp.TOTP(enrolment.secret).now())
    return issued
