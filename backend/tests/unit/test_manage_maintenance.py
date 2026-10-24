"""Who may close the platform, and what a second press does (#61)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_maintenance import ManageMaintenance, assert_serving
from app.domain.entities.actor import ADMIN_ONLY_SCOPES, ROLE_SCOPES, Actor, Role, Scope
from app.domain.entities.maintenance import NORMAL
from app.domain.exceptions import (
    MaintenanceDisabledError,
    MaintenanceError,
    MaintenanceStateConflictError,
    NotAuthorizedError,
)
from tests.unit.fakes import FakeAudit, FakeMaintenance

ADMIN = Actor(
    id="admin-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
)
TENANT_ADMIN = Actor(
    id="ta-1",
    display="lead",
    role=Role.TENANT_ADMIN,
    source="tailnet",
    scopes=ROLE_SCOPES[Role.TENANT_ADMIN],
)
FORGED = Actor(
    id="svc", display="key", role=Role.SERVICE, source="api_key", scopes=frozenset(Scope)
)
"""An actor whose scopes say everything and whose role says API key: the role
check is what refuses it."""


def build(*, enabled: bool = True) -> tuple[ManageMaintenance, FakeMaintenance, FakeAudit]:
    repo = FakeMaintenance()
    audit = FakeAudit()
    return ManageMaintenance(repo, RoleAuthorization(), audit, enabled=enabled), repo, audit


def test_only_platform_admins_hold_the_maintenance_scopes() -> None:
    assert {Scope.MAINTENANCE_READ, Scope.MAINTENANCE_WRITE} <= ADMIN_ONLY_SCOPES
    for role, scopes in ROLE_SCOPES.items():
        if role is not Role.ADMIN:
            assert Scope.MAINTENANCE_WRITE not in scopes, role


@pytest.mark.parametrize("actor", [TENANT_ADMIN, FORGED])
async def test_nobody_but_a_platform_admin_can_close_or_read(actor: Actor) -> None:
    use_case, repo, _ = build()
    with pytest.raises(NotAuthorizedError):
        await use_case.enter(actor, message=None, expected_return_at=None)
    with pytest.raises(NotAuthorizedError):
        await use_case.status(actor)
    assert repo.state.admission_closed is False


async def test_entering_twice_is_one_hold_and_one_audit_row() -> None:
    use_case, _, audit = build()
    first = await use_case.enter(ADMIN, message="  Upgrading  ", expected_return_at=None)
    second = await use_case.enter(ADMIN, message="other", expected_return_at=None)

    assert first.epoch == second.epoch == 1
    assert second.message == "Upgrading"
    assert [e[0] for e in audit.entries] == ["maintenance.entered"]


async def test_entering_is_refused_while_disabled_and_reopening_is_not() -> None:
    use_case, repo, _ = build(enabled=False)
    with pytest.raises(MaintenanceDisabledError):
        await use_case.enter(ADMIN, message=None, expected_return_at=None)

    repo.state = replace(repo.state, admission_closed=True, epoch=2)
    reopened = await use_case.reopen(ADMIN)
    assert reopened.admission_closed is False
    assert reopened.epoch == 2, "reopening never rewinds the epoch"


async def test_a_message_edit_against_a_stale_read_is_refused() -> None:
    use_case, _, _ = build()
    entered = await use_case.enter(ADMIN, message="a", expected_return_at=None)
    await use_case.set_message(
        ADMIN, message="b", expected_return_at=None, expected_revision=entered.revision
    )
    with pytest.raises(MaintenanceStateConflictError):
        await use_case.set_message(
            ADMIN, message="c", expected_return_at=None, expected_revision=entered.revision
        )


async def test_assert_serving_refuses_everyone_while_closed() -> None:
    repo = FakeMaintenance()
    await assert_serving(repo)
    repo.state = replace(repo.state, admission_closed=True)
    with pytest.raises(MaintenanceError):
        await assert_serving(repo)


def test_only_an_admin_session_survives_an_entry() -> None:
    closed = replace(NORMAL, admission_closed=True, epoch=4)
    assert closed.session_valid(3, platform_admin=True)
    assert not closed.session_valid(3, platform_admin=False)
    assert closed.session_valid(4, platform_admin=False)
    reopened = replace(closed, admission_closed=False)
    assert not reopened.session_valid(3, platform_admin=False), "revoked stays revoked"
