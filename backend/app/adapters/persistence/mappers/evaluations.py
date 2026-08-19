"""Persistence evaluations boundary."""

from __future__ import annotations

from app.adapters.persistence.sqlalchemy_models import (
    EvaluationModelScoreRow,
    EvaluationRunRow,
    EvaluationTaskScoreRow,
)
from app.domain.entities.evaluation import (
    EvaluationModelScore,
    EvaluationRun,
    EvaluationTaskScore,
)


def evaluation_run_to_domain(row: EvaluationRunRow) -> EvaluationRun:
    return EvaluationRun(
        id=row.id,
        label=row.label,
        phase=row.phase,
        ran_at=row.ran_at,
        harness_ref=row.harness_ref,
        sample_count=row.sample_count,
        # `str(v)` because the column is JSON and hands back `Any`, the same
        # coercion `prompt_log_row_to_domain` applies to its own JSON column.
        caveats=tuple(str(v) for v in (row.caveats or [])),
        note=row.note,
        imported_at=row.imported_at,
        imported_by=row.imported_by or None,
    )


def evaluation_model_score_to_domain(row: EvaluationModelScoreRow) -> EvaluationModelScore:
    return EvaluationModelScore(
        model_ref=row.model_ref,
        score=row.score,
        scored_samples=row.scored_samples,
        no_result_samples=row.no_result_samples,
        generation_tokens_per_second=row.generation_tokens_per_second,
        prompt_depth_tokens=row.prompt_depth_tokens,
        seconds_per_round_min=row.seconds_per_round_min,
        seconds_per_round_max=row.seconds_per_round_max,
    )


def evaluation_task_score_to_domain(row: EvaluationTaskScoreRow) -> EvaluationTaskScore:
    return EvaluationTaskScore(
        model_ref=row.model_ref,
        task=row.task,
        group=row.task_group,
        score=row.score,
        samples=row.samples,
    )
