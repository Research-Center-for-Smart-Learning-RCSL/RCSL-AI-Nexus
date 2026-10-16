"""Residency intent on the model lifecycle (#49 §1, §3) and the occupancy rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.audit_subject import RESIDENCY_RECONCILER_ID
from app.application.use_cases.manage_models import ManageModels
from app.domain.entities.audit import AuditAction
from app.domain.entities.model import ModelState, ResourceProfile, RuntimeKind
from app.domain.exceptions import InsufficientMemoryError, NotAuthorizedError
from app.domain.services.memory_budget_service import MemoryBudgetService
from app.shared.clock import FixedClock
from tests.unit.fakes import FakeStateCommitter
from tests.unit.manage_models_fixtures import ADMIN, READER, Harness, make_model

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


async def test_an_operator_load_records_the_wish_to_keep_it_resident() -> None:
    harness = Harness([make_model()])
    loaded = await harness.use_case.load(ADMIN, "m1")
    assert loaded.desired_resident is True
    assert loaded.desired_version == 1


async def test_an_operator_unload_withdraws_it() -> None:
    harness = Harness([make_model(state=ModelState.LOADED, desired_resident=True)])
    unloaded = await harness.use_case.unload(ADMIN, "m1")
    assert harness.models.rows["m1"].desired_resident is False
    assert harness.models.rows["m1"].desired_version == 1
    assert unloaded.state is ModelState.DOWNLOADED


async def test_intent_changes_without_touching_the_runtime_and_is_audited_as_accepted() -> None:
    """The cancellation after a restart: observed `downloaded`, which `unload`
    refuses, and the operator still has to be able to stop the restore."""
    after_restart = make_model(
        state=ModelState.LOADED,
        observed_state=ModelState.DOWNLOADED,
        observed_at=NOW,
        desired_resident=True,
        desired_version=4,
    )
    harness = Harness([after_restart])

    changed = await harness.use_case.set_desired_residency(ADMIN, "m1", False)

    assert changed.desired_resident is False
    assert changed.desired_version == 5
    assert changed.state is ModelState.LOADED, "lifecycle state is left alone"
    assert harness.runtime.loaded == [] and harness.runtime.unloaded == []
    actor, action, target, outcome, detail = harness.audit.rows[-1]
    assert action is AuditAction.MODEL_RESIDENCY_INTENT_CHANGED
    assert (actor.id, target, outcome) == (ADMIN.id, "m1", "accepted")
    assert detail == {"desired_resident": "false", "desired_version": "5"}


async def test_changing_intent_needs_model_write() -> None:
    harness = Harness([make_model()])
    with pytest.raises(NotAuthorizedError):
        await harness.use_case.set_desired_residency(READER, "m1", True)
    assert harness.models.rows["m1"].desired_version == 0


async def test_a_restore_loads_without_writing_intent() -> None:
    """A load in flight must not restore a flag withdrawn meanwhile."""
    harness = Harness([make_model(desired_resident=False, desired_version=7)])

    restored = await harness.use_case.restore("m1")

    assert harness.runtime.loaded == ["library/qwen2.5:7b"]
    assert restored.state is ModelState.LOADED
    assert (restored.desired_resident, restored.desired_version) == (False, 7)
    actor, action, *_ = harness.audit.rows[-1]
    assert action is AuditAction.MODEL_LOADED
    assert actor.id == RESIDENCY_RECONCILER_ID
    assert not actor.scopes, "a label for the audit row, never a credential"


async def test_a_release_unloads_without_writing_intent() -> None:
    harness = Harness([make_model(state=ModelState.LOADED, desired_version=3)])
    await harness.use_case.release("m1")
    assert harness.runtime.unloaded == ["library/qwen2.5:7b"]
    assert harness.models.rows["m1"].desired_version == 3


def _budgeted(harness: Harness, *, frees: bool) -> ManageModels:
    return ManageModels(
        models=harness.models,
        nodes=harness.nodes,
        policies=harness.policies,
        runtimes={RuntimeKind.OLLAMA: harness.runtime},
        budget=MemoryBudgetService(),
        state_committer=FakeStateCommitter(harness.models),
        authz=RoleAuthorization(),
        audit=harness.audit,
        observed_absence_frees_memory=frees,
        clock=FixedClock(NOW),
    )


def _after_restart(observed_at: datetime) -> Harness:
    # 70 GB whose intent says loaded, but the runtime freshly says it is not.
    gone = make_model(
        id="big",
        alias="big",
        ref="big:tag",
        state=ModelState.LOADED,
        observed_state=ModelState.DOWNLOADED,
        observed_at=observed_at,
        resource_profile=ResourceProfile(memory_gb=70.0, context_length=8192),
    )
    return Harness([gone, make_model()])


async def test_budget_is_unchanged_while_the_reconciler_is_off() -> None:
    harness = _after_restart(NOW - timedelta(seconds=5))
    with pytest.raises(InsufficientMemoryError):
        await _budgeted(harness, frees=False).load(ADMIN, "m1")


async def test_a_fresh_absence_is_not_charged_when_it_is_on() -> None:
    harness = _after_restart(NOW - timedelta(seconds=5))
    loaded = await _budgeted(harness, frees=True).restore("m1")
    assert loaded.state is ModelState.LOADED


async def test_a_stale_absence_is_still_charged_when_it_is_on() -> None:
    harness = _after_restart(NOW - timedelta(minutes=10))
    with pytest.raises(InsufficientMemoryError):
        await _budgeted(harness, frees=True).restore("m1")
