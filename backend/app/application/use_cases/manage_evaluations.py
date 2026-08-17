"""Reading stored capability evaluations, and loading one.

**The scopes are `model:read` and `model:write`, not a pair of new ones.** An
evaluation says what a model did on a task set; its audience is exactly the
audience for the model registry, and its writer is exactly whoever may change
what the registry holds. A dedicated `evaluation:read` would have been granted
to the same four roles and withheld from the same two, which is a name without
a decision behind it -- and `role_authorization.py` argues that every scope
placement should carry one. The cost of reusing them is stated rather than
hidden: an operator who may register a model may also replace the evidence
about it, and the audit row for the import is what makes that recoverable.

**Reading is not audited and importing is.** The read discloses a table of
scores about models, which is not sensitive and would fire on every page
refresh -- the same reasoning `ReadPromptLogs` uses for not auditing its list.
The import replaces what a later routing decision will cite, and a run arriving
with a label that already exists overwrites the earlier numbers, so the audit
row is the only place the previous reading is recorded as having existed.

**`import_run` takes samples and does the arithmetic itself, after the scope
check.** It took a finished `EvaluationReport` first, which meant the router
aggregated the request body *before* this class had refused anybody: a caller
with no evaluation scopes at all -- any account with a session -- could spend
the admin process's CPU on a body it was never going to be allowed to store.
Reducing samples is cheap per sample and unbounded in aggregate, so it belongs
behind the check rather than in front of it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.evaluation import (
    EvaluationReport,
    EvaluationRun,
    EvaluationSample,
    aggregate,
)
from app.domain.exceptions import EvaluationRunNotFoundError
from app.domain.ports.repositories import EvaluationRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.shared.clock import Clock


class ManageEvaluations:
    def __init__(
        self,
        evaluations: EvaluationRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._evaluations = evaluations
        self._authz = authz
        self._audit = audit
        self._clock = clock

    async def list_runs(self, actor: Actor) -> list[EvaluationRun]:
        self._authz.require(actor, Scope.MODEL_READ)
        return await self._evaluations.list_runs()

    async def latest(self, actor: Actor) -> EvaluationReport | None:
        """The newest run by when it ran, or None when nothing is stored.

        None rather than a 404: a deployment that has never run the task set is
        in a normal state, and the screen says so. A missing *named* run is the
        opposite -- somebody followed a link to something that is gone -- which
        is why `report` raises and this does not.
        """
        self._authz.require(actor, Scope.MODEL_READ)
        return await self._evaluations.latest_report()

    async def report(self, actor: Actor, run_id: str) -> EvaluationReport:
        self._authz.require(actor, Scope.MODEL_READ)
        report = await self._evaluations.get_report(run_id)
        if report is None:
            raise EvaluationRunNotFoundError(detail=f"no evaluation run {run_id}")
        return report

    async def import_run(
        self,
        actor: Actor,
        samples: Sequence[EvaluationSample],
        *,
        label: str,
        phase: str,
        ran_at: datetime,
        harness_ref: str,
        caveats: Sequence[str] = (),
        note: str = "",
    ) -> EvaluationReport:
        """Reduce a run's samples to scores and store it, replacing its label.

        The scope check is the first statement for the reason in this module's
        docstring. The arithmetic itself stays in the domain
        (`entities/evaluation.aggregate`) rather than moving here: it is a pure
        calculation with a published reading to match, and it is tested against
        that reading rather than through a use case holding a repository and an
        audit port.

        `imported_at` is stamped from the clock rather than left to the column's
        default, so the report this returns carries the same timestamp the row
        does. Left to the default, the `201` from an import always said the run
        had never been loaded.
        """
        self._authz.require(actor, Scope.MODEL_WRITE)

        report = aggregate(
            samples,
            run_id=str(uuid.uuid4()),
            label=label,
            phase=phase,
            ran_at=ran_at,
            harness_ref=harness_ref,
            caveats=caveats,
            note=note,
        )
        stored = EvaluationReport(
            # Both fields are taken here rather than trusted from the caller: a
            # field naming who loaded something, and when, is worth nothing if
            # the loader fills it in.
            run=replace(
                report.run,
                imported_by=actor.display,
                imported_at=self._clock.now(),
            ),
            models=report.models,
            tasks=report.tasks,
        )
        await self._evaluations.save_report(stored)
        await self._audit.record(
            actor,
            AuditAction.EVALUATION_IMPORTED,
            target=stored.run.id,
            detail={
                "label": stored.run.label,
                "phase": stored.run.phase,
                "samples": str(stored.run.sample_count),
                "models": ", ".join(stored.model_refs),
            },
        )
        return stored

    async def delete_run(self, actor: Actor, run_id: str) -> None:
        self._authz.require(actor, Scope.MODEL_WRITE)
        if not await self._evaluations.delete_run(run_id):
            raise EvaluationRunNotFoundError(detail=f"no evaluation run {run_id}")
        await self._audit.record(actor, AuditAction.EVALUATION_DELETED, target=run_id, detail={})
