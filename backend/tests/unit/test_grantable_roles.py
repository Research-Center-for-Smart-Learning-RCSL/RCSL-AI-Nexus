"""You cannot grant authority you do not hold.

`Scope.USER_WRITE` answers "may this caller create and edit accounts" and says
nothing about with which role. With two roles that gap was unreachable — the
only holder was `admin`, and there was nothing above it. Adding `tenant_admin`
turned it into a one-request path to platform administrator: invite an account
with `role: admin`, take the single-use onboarding link out of the same
response body, and hold `frozenset(Scope)` a minute later.

That reaches well outside the tenant the role is confined to, because the
confinement is repository-level and applies to users, keys, usage and
knowledge — nodes, models, routing policies and tenants are platform-global.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import NotAuthorizedError
from app.domain.services.grantable_roles import assert_may_grant

AUTHZ = RoleAuthorization()


def actor_with(role: Role) -> Actor:
    return Actor(
        id=f"u-{role.value}",
        display=role.value,
        role=role,
        source="local",
        scopes=AUTHZ.scopes_for(role.value),
    )


def grantable(role: Role) -> set[Role]:
    holder = actor_with(role)
    allowed = set()
    for candidate in Role:
        try:
            assert_may_grant(AUTHZ, holder, candidate)
        except NotAuthorizedError:
            continue
        allowed.add(candidate)
    return allowed


def test_a_tenant_admin_cannot_manufacture_a_platform_admin() -> None:
    """The escalation itself, stated as the test it failed."""
    with pytest.raises(NotAuthorizedError) as caught:
        assert_may_grant(AUTHZ, actor_with(Role.TENANT_ADMIN), Role.ADMIN)
    assert "tenant:write" in str(caught.value), "the message names what would be conferred"


def test_a_tenant_admin_cannot_grant_the_fleet_either() -> None:
    """`operator` holds `NODE_WRITE`, `MODEL_WRITE` and `ROUTING_WRITE`, none of
    which a `tenant_admin` has. Handing them out is the same escalation wearing
    a smaller hat: the grantee acts, and the granter chose that they could."""
    with pytest.raises(NotAuthorizedError):
        assert_may_grant(AUTHZ, actor_with(Role.TENANT_ADMIN), Role.OPERATOR)


def test_a_tenant_admin_can_still_run_its_own_tenant() -> None:
    """The rule has to leave the role usable, or it is just a ban."""
    assert grantable(Role.TENANT_ADMIN) == {
        Role.TENANT_ADMIN,
        Role.CURATOR,
        Role.AUDITOR,
        Role.USER,
        Role.SERVICE,
    }


def test_an_admin_can_grant_anything() -> None:
    assert grantable(Role.ADMIN) == set(Role)


def test_the_rule_is_reflexive_for_every_role() -> None:
    """Nobody is blocked from granting their own role. It confers exactly what
    the granter already holds, so it moves no authority anywhere."""
    for role in Role:
        assert_may_grant(AUTHZ, actor_with(role), role)


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.CURATOR, Role.AUDITOR, Role.USER])
def test_roles_without_user_write_are_stopped_earlier_anyway(role: Role) -> None:
    """Belt and braces, and worth asserting: these never reach the rule at all
    because they lack `USER_WRITE`, so a change that weakened the rule would
    still not hand them anything."""
    assert Scope.USER_WRITE not in AUTHZ.scopes_for(role.value)
