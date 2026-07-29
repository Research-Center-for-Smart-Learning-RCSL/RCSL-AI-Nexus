"""Tenant management: creating a tenant bootstraps its first admin into it.

The load-bearing behaviours: creating a tenant mints a first administrator in
*that* tenant (not the caller's) with an onboarding link, a duplicate name is
refused, and both operations require the tenant scopes.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.manage_tenants import ManageTenants
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.tenant import Tenant
from app.domain.exceptions import ModelStateConflictError, NotAuthorizedError
from app.domain.services.token_service import TokenService
from app.shared.clock import SystemClock
from tests.unit.fakes import FakeAudit, FakeInvitations, FakeTenants, FakeUsers

ADMIN = Actor(id="a1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope))
PLAIN_USER = Actor(
    id="u1", display="user", role=Role.USER, source="local", scopes=frozenset({Scope.CHAT_USE})
)


def build(tenants=()) -> tuple[ManageTenants, FakeUsers, FakeAudit]:
    users = FakeUsers()
    audit = FakeAudit()
    invite = IssueInvitation(
        users=users,
        invitations=FakeInvitations(),
        tokens=TokenService(),
        audit=audit,
        authz=RoleAuthorization(),
        clock=SystemClock(),
        ttl_seconds=3600,
    )
    use_case = ManageTenants(
        tenants=FakeTenants(tenants),
        invite=invite,
        authz=RoleAuthorization(),
        audit=audit,
    )
    return use_case, users, audit


async def test_create_bootstraps_a_first_admin_into_the_new_tenant() -> None:
    tenants, users, audit = build()

    created = await tenants.create(
        ADMIN,
        name="Vision Lab",
        first_admin_login="Lead@Example.org",
        first_admin_display_name="Lead",
    )

    assert created.tenant.name == "Vision Lab"
    assert created.invitation.token, "the first admin's onboarding link is returned once"

    admin_user = await users.get_by_login("lead@example.org")
    assert admin_user is not None
    assert admin_user.tenant_id == created.tenant.id, "the first admin lands in the new tenant"
    assert admin_user.role is Role.ADMIN
    assert "tenant.created" in audit.actions()


async def test_create_refuses_a_duplicate_name() -> None:
    tenants, _, _ = build(tenants=[Tenant(id="t1", name="Existing")])

    with pytest.raises(ModelStateConflictError):
        await tenants.create(
            ADMIN,
            name="Existing",
            first_admin_login="x@example.org",
            first_admin_display_name="X",
        )


async def test_create_requires_tenant_write() -> None:
    tenants, _, _ = build()

    with pytest.raises(NotAuthorizedError):
        await tenants.create(
            PLAIN_USER,
            name="Nope",
            first_admin_login="x@example.org",
            first_admin_display_name="X",
        )


async def test_list_requires_tenant_read_and_returns_all() -> None:
    tenants, _, _ = build(tenants=[Tenant(id="t1", name="A"), Tenant(id="t2", name="B")])

    with pytest.raises(NotAuthorizedError):
        await tenants.list_all(PLAIN_USER)

    assert {t.name for t in await tenants.list_all(ADMIN)} == {"A", "B"}
