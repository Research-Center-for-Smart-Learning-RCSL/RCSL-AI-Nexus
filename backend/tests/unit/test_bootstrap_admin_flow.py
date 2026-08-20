from __future__ import annotations

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.domain.entities.actor import Role
from tests.unit.fakes import (
    FakeAudit,
    FakeUsers,
)

pytest_plugins = ("tests.unit.invitation_flow_fixtures",)


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
