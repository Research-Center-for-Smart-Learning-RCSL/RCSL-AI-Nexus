"""Persistence evaluations boundary."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    EvaluationModelScoreRow,
    EvaluationRunRow,
    EvaluationTaskScoreRow,
)
from app.domain.entities.evaluation import (
    EvaluationReport,
    EvaluationRun,
)

from .shared import _Base


class PostgresEvaluationRepository(_Base):
    """Stored capability evaluations. No tenant scope: they describe the fleet.

    Every read here returns whole runs. There is no paged variant and none is
    needed -- a run is one table of models against tasks, and the number of
    runs is the number of times somebody has spent an afternoon measuring
    models, which on this deployment is a figure in the single digits.
    """

    async def list_runs(self) -> list[EvaluationRun]:
        rows = await self._session.scalars(
            select(EvaluationRunRow).order_by(EvaluationRunRow.ran_at.desc())
        )
        return [m.evaluation_run_to_domain(row) for row in rows]

    async def get_report(self, run_id: str) -> EvaluationReport | None:
        row = await self._session.get(EvaluationRunRow, run_id)
        return await self._assemble(row) if row else None

    async def latest_report(self) -> EvaluationReport | None:
        row = await self._session.scalar(
            select(EvaluationRunRow).order_by(EvaluationRunRow.ran_at.desc()).limit(1)
        )
        return await self._assemble(row) if row else None

    async def _assemble(self, run: EvaluationRunRow) -> EvaluationReport:
        models = await self._session.scalars(
            select(EvaluationModelScoreRow)
            .where(EvaluationModelScoreRow.run_id == run.id)
            .order_by(EvaluationModelScoreRow.model_ref)
        )
        tasks = await self._session.scalars(
            select(EvaluationTaskScoreRow)
            .where(EvaluationTaskScoreRow.run_id == run.id)
            .order_by(EvaluationTaskScoreRow.id)
        )
        return EvaluationReport(
            run=m.evaluation_run_to_domain(run),
            models=tuple(m.evaluation_model_score_to_domain(row) for row in models),
            # Ordered by id, which the writer assigns in the aggregate's own
            # order: the harness emits tasks in the order the set is meant to
            # be read, and the groups mean something in that order. Sorting
            # alphabetically here would silently reorder the screen's rows.
            tasks=tuple(m.evaluation_task_score_to_domain(row) for row in tasks),
        )

    async def save_report(self, report: EvaluationReport) -> None:
        # Delete by label rather than by id: a corrected re-import arrives with
        # a fresh id and the same label, and the label is what an operator
        # thinks of as "the run". The children go with it through the cascade.
        await self._session.execute(
            delete(EvaluationRunRow).where(EvaluationRunRow.label == report.run.label)
        )
        await self._session.flush()

        self._session.add(
            EvaluationRunRow(
                id=report.run.id,
                label=report.run.label,
                phase=report.run.phase,
                ran_at=report.run.ran_at,
                harness_ref=report.run.harness_ref,
                sample_count=report.run.sample_count,
                caveats=list(report.run.caveats),
                note=report.run.note,
                imported_by=report.run.imported_by or "",
                # Written rather than left to the column default, so the row
                # and the response the importer just returned carry the same
                # timestamp. `None` falls back to the default for the paths
                # that do not stamp one.
                **(
                    {"imported_at": report.run.imported_at}
                    if report.run.imported_at is not None
                    else {}
                ),
            )
        )
        # Flushed before the children, not with them. There is no ORM
        # relationship between these tables — the repository assembles the
        # aggregate itself — so SQLAlchemy has nothing to order the inserts by
        # and put the scores in first, against a foreign key whose parent did
        # not exist yet.
        await self._session.flush()

        for index, model in enumerate(report.models):
            self._session.add(
                EvaluationModelScoreRow(
                    id=f"{report.run.id}:m{index:03d}",
                    run_id=report.run.id,
                    model_ref=model.model_ref,
                    score=model.score,
                    scored_samples=model.scored_samples,
                    no_result_samples=model.no_result_samples,
                    generation_tokens_per_second=model.generation_tokens_per_second,
                    prompt_depth_tokens=model.prompt_depth_tokens,
                    seconds_per_round_min=model.seconds_per_round_min,
                    seconds_per_round_max=model.seconds_per_round_max,
                )
            )
        for index, task in enumerate(report.tasks):
            # The index is zero-padded so that ordering by id is ordering by
            # the aggregate's own sequence. Unpadded, `:t10` sorts before `:t9`
            # and the screen's task order stops matching the task set's.
            self._session.add(
                EvaluationTaskScoreRow(
                    id=f"{report.run.id}:t{index:04d}",
                    run_id=report.run.id,
                    model_ref=task.model_ref,
                    task=task.task,
                    task_group=task.group,
                    score=task.score,
                    samples=task.samples,
                )
            )
        await self._session.flush()

    async def delete_run(self, run_id: str) -> bool:
        result = await self._session.execute(
            delete(EvaluationRunRow).where(EvaluationRunRow.id == run_id)
        )
        return cast(CursorResult[Any], result).rowcount > 0
