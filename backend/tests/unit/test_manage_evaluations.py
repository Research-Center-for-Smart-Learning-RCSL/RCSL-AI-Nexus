"""Who may read an evaluation, who may load one, and what the log says after.

The reason this file exists rather than trusting the scope declarations: the
evaluation screen reuses `model:read` and `model:write` instead of minting a
pair of its own, and a reused scope is exactly the kind that gets attached to
the wrong verb without anybody noticing. So the split is pinned here — reading
must not need the write, and importing must not be reachable with the read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_evaluations import ManageEvaluations
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.evaluation import EvaluationReport, EvaluationSample, aggregate
from app.domain.exceptions import EvaluationRunNotFoundError, NotAuthorizedError
from tests.unit.fakes import FakeAudit

RAN_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def actor(*scopes: Scope) -> Actor:
    return Actor(
        id="u1",
        display="operator@example.test",
        role=Role.OPERATOR,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t1",
    )


def report(label: str = "a run") -> EvaluationReport:
    return aggregate(
        [EvaluationSample(model_ref="m1", task="t1", group="A", round_index=0, score=1.0)],
        run_id="run-1",
        label=label,
        phase="full",
        ran_at=RAN_AT,
        harness_ref="scripts/model-eval",
    )


class FakeEvaluations:
    """Keyed by label rather than by id, which is the property under test:
    `save_report` replaces a run carrying the same label."""

    def __init__(self) -> None:
        self.by_label: dict[str, EvaluationReport] = {}
        self.deleted: list[str] = []

    async def list_runs(self):
        return [stored.run for stored in self.by_label.values()]

    async def get_report(self, run_id: str):
        return next(
            (r for r in self.by_label.values() if r.run.id == run_id),
            None,
        )

    async def latest_report(self):
        runs = sorted(self.by_label.values(), key=lambda r: r.run.ran_at, reverse=True)
        return runs[0] if runs else None

    async def save_report(self, stored: EvaluationReport) -> None:
        self.by_label[stored.run.label] = stored

    async def delete_run(self, run_id: str) -> bool:
        found = next((r for r in self.by_label.values() if r.run.id == run_id), None)
        if found is None:
            return False
        del self.by_label[found.run.label]
        self.deleted.append(run_id)
        return True


def build() -> tuple[ManageEvaluations, FakeEvaluations, FakeAudit]:
    store, audit = FakeEvaluations(), FakeAudit()
    return (
        ManageEvaluations(evaluations=store, authz=RoleAuthorization(), audit=audit),
        store,
        audit,
    )


@pytest.mark.asyncio
async def test_reading_needs_model_read_and_not_the_write() -> None:
    use_case, store, _ = build()
    await store.save_report(report())

    assert await use_case.list_runs(actor(Scope.MODEL_READ)) != []
    assert await use_case.latest(actor(Scope.MODEL_READ)) is not None


@pytest.mark.asyncio
async def test_reading_is_refused_without_model_read() -> None:
    use_case, _, _ = build()
    with pytest.raises(NotAuthorizedError):
        await use_case.list_runs(actor(Scope.CHAT_USE))


@pytest.mark.asyncio
async def test_importing_is_refused_to_a_reader() -> None:
    """The half that matters. `model:read` reaches four roles; if it also
    admitted an import, an auditor could replace the evidence they are there
    to read."""
    use_case, _, _ = build()
    with pytest.raises(NotAuthorizedError):
        await use_case.import_run(actor(Scope.MODEL_READ), report())


@pytest.mark.asyncio
async def test_an_import_is_audited_and_names_what_it_loaded() -> None:
    use_case, _, audit = build()
    await use_case.import_run(actor(Scope.MODEL_WRITE), report())

    (row,) = audit.rows
    _, action, target, outcome, detail = row
    assert action == "evaluation.imported"
    assert target == "run-1"
    assert outcome == "success"
    assert detail["label"] == "a run"
    assert detail["models"] == "m1"


@pytest.mark.asyncio
async def test_the_importer_is_recorded_from_the_actor_not_from_the_payload() -> None:
    """A field naming who loaded something is worth nothing if the loader
    fills it in."""
    use_case, store, _ = build()
    stored = await use_case.import_run(actor(Scope.MODEL_WRITE), report())

    assert stored.run.imported_by == "operator@example.test"
    assert store.by_label["a run"].run.imported_by == "operator@example.test"


@pytest.mark.asyncio
async def test_a_missing_run_is_a_not_found_rather_than_an_empty_report() -> None:
    use_case, _, _ = build()
    with pytest.raises(EvaluationRunNotFoundError):
        await use_case.report(actor(Scope.MODEL_READ), "nope")


@pytest.mark.asyncio
async def test_latest_is_none_on_a_deployment_that_has_never_run_the_set() -> None:
    """Not an error: running the task set is an afternoon's work nobody owes
    anyone, and a deployment without one is in a normal state."""
    use_case, _, _ = build()
    assert await use_case.latest(actor(Scope.MODEL_READ)) is None


@pytest.mark.asyncio
async def test_deleting_a_run_that_is_not_there_is_refused_rather_than_silent() -> None:
    use_case, _, audit = build()
    with pytest.raises(EvaluationRunNotFoundError):
        await use_case.delete_run(actor(Scope.MODEL_WRITE), "nope")
    assert audit.rows == []


@pytest.mark.asyncio
async def test_a_delete_is_audited() -> None:
    use_case, _, audit = build()
    await use_case.import_run(actor(Scope.MODEL_WRITE), report())
    await use_case.delete_run(actor(Scope.MODEL_WRITE), "run-1")

    assert audit.actions() == ["evaluation.imported", "evaluation.deleted"]
