"""The shape of the authorization table, asserted rather than assumed.

`_ADMIN_SCOPES` is `frozenset(Scope)`, so every scope added from now on lands
in `admin` automatically and in no other role. That is correct for `admin` and
is exactly how the roles below rot: a new feature ships, only administrators
can reach it, and the role that was supposed to cover that area quietly falls
behind with nothing to say so. The same failure as the health script that
listed nine of eleven services.

So the rule is written down: every scope reaches some role other than `admin`,
unless it is named in `ADMIN_ONLY_SCOPES` with its reason.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import (
    ADMIN_ONLY_SCOPES,
    ASSIGNABLE_ROLES,
    ROLE_SCOPES,
    RoleAuthorization,
)
from app.domain.entities.actor import Actor, Role, Scope

WRITE_SCOPES = frozenset(s for s in Scope if "write" in s.value)


def test_every_scope_reaches_a_role_other_than_admin() -> None:
    """The guard against silent narrowing. A new scope must be placed, or
    argued for in `ADMIN_ONLY_SCOPES`; doing neither fails here rather than
    quietly making a role less useful than its docstring claims."""
    reachable = set()
    for role, scopes in ROLE_SCOPES.items():
        if role is Role.ADMIN:
            continue
        reachable |= scopes

    unplaced = set(Scope) - reachable - ADMIN_ONLY_SCOPES
    assert not unplaced, (
        f"{sorted(s.value for s in unplaced)} reach only `admin`. Either grant them to the "
        "role that should own them, or add them to ADMIN_ONLY_SCOPES with the reason."
    )


def test_admin_only_scopes_really_are_admin_only() -> None:
    """The other direction: an entry here that some role does hold is a stale
    claim, and a stale claim in this file is worse than none."""
    for scope in ADMIN_ONLY_SCOPES:
        holders = [r.value for r, s in ROLE_SCOPES.items() if r is not Role.ADMIN and scope in s]
        assert not holders, f"{scope.value} is listed as admin-only but {holders} hold it"


def test_admin_holds_everything() -> None:
    assert ROLE_SCOPES[Role.ADMIN] == frozenset(Scope)


def test_every_role_is_in_the_table() -> None:
    """A role in the enum with no entry resolves to an empty scope set, which
    presents as an account that can do nothing rather than as a wiring error."""
    assert set(ROLE_SCOPES) == set(Role)


def test_service_holds_no_control_plane_scope() -> None:
    """An API key is never a person. Whatever capability list it was issued
    with, it cannot reach the control plane."""
    assert ROLE_SCOPES[Role.SERVICE] <= {Scope.CHAT_USE, Scope.USAGE_READ_OWN}


def test_service_is_not_assignable_to_a_person() -> None:
    assert Role.SERVICE not in ASSIGNABLE_ROLES
    assert set(ASSIGNABLE_ROLES) == set(Role) - {Role.SERVICE}


def test_auditor_can_write_nothing() -> None:
    """The whole content of the role. It includes dropping `API_KEY_WRITE_OWN`,
    which the base set grants everyone else: an auditor who can mint a key can
    act through the gateway, and then the record of their visit is no longer
    only a read."""
    assert not (ROLE_SCOPES[Role.AUDITOR] & WRITE_SCOPES)


def test_operator_cannot_grant_access() -> None:
    """The split this role exists for. An operator who can issue a key or
    promote an account can hand themselves every other scope, which would make
    the boundary a delay rather than a limit."""
    operator = ROLE_SCOPES[Role.OPERATOR]
    assert Scope.USER_WRITE not in operator
    assert Scope.API_KEY_WRITE_ANY not in operator
    assert Scope.TENANT_WRITE not in operator
    # And it really can run the fleet, so the role is worth having.
    assert {Scope.MODEL_WRITE, Scope.NODE_WRITE, Scope.ROUTING_WRITE} <= operator


def test_tenant_admin_cannot_touch_the_platform() -> None:
    """Its authority is total inside one tenant and absent outside it. The
    confinement itself is structural — `di.py` hands it a tenant-scoped
    repository — so what is asserted here is only the other half: it holds no
    write that reaches beyond a tenant."""
    tenant_admin = ROLE_SCOPES[Role.TENANT_ADMIN]
    assert {Scope.USER_WRITE, Scope.API_KEY_WRITE_ANY, Scope.KNOWLEDGE_WRITE} <= tenant_admin
    for platform_write in (
        Scope.TENANT_WRITE,
        Scope.NODE_WRITE,
        Scope.MODEL_WRITE,
        Scope.ROUTING_WRITE,
    ):
        assert platform_write not in tenant_admin


def test_curator_reaches_the_knowledge_base_and_nothing_else() -> None:
    curator = ROLE_SCOPES[Role.CURATOR]
    assert {Scope.KNOWLEDGE_READ, Scope.KNOWLEDGE_WRITE} <= curator
    assert not (curator & {Scope.USER_WRITE, Scope.MODEL_WRITE, Scope.NODE_WRITE})


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.SERVICE])
def test_every_human_role_can_use_the_chat(role: Role) -> None:
    """Including `auditor`. A role whose holder cannot ask a question is one
    nobody accepts being put in, and chat changes no configuration."""
    assert Scope.CHAT_USE in ROLE_SCOPES[role]


def test_require_refuses_a_scope_the_role_lacks() -> None:
    authz = RoleAuthorization()
    actor = Actor(
        id="u-1",
        display="someone",
        role=Role.OPERATOR,
        source="local",
        scopes=authz.scopes_for(Role.OPERATOR.value),
    )

    authz.require(actor, Scope.NODE_WRITE)  # held, so silent

    with pytest.raises(Exception) as caught:
        authz.require(actor, Scope.USER_WRITE)
    assert "user:write" in str(caught.value)
