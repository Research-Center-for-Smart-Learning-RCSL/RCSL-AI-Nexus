"""Issuing and redeeming links, and the first-admin bootstrap.

The cases worth pinning are the ones where a correct-looking implementation
still fails: a link that survives its use, a mistyped code that burns the
link anyway, an account that ends up with a password but no second factor,
and a bootstrap that fires twice because a page load made several requests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.redis_adapter import InMemoryCache
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.application.use_cases.accept_invitation import AcceptInvitation
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.domain.entities.actor import Actor, Role, Scope
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


async def _enrol(harness: Harness):
    issued = await harness.issue.create_account(
        ADMIN, login="new@example.org", display_name="New", role=Role.USER
    )
    enrolment = await harness.accept.begin(issued.token)
    await harness.accept.complete(issued.token, STRONG_PASSWORD, pyotp.TOTP(enrolment.secret).now())
    return issued
