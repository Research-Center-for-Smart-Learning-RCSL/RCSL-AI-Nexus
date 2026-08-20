"""Evaluation aggregation and scoring services."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from datetime import datetime

from .entities import (
    DISCRIMINATION_THRESHOLD,
    EvaluationModelScore,
    EvaluationReport,
    EvaluationRun,
    EvaluationSample,
    EvaluationTaskScore,
    TaskVerdict,
)


def _verdict_for(scores: Sequence[float]) -> TaskVerdict:
    if not scores:  # pragma: no cover - `verdicts` filters these out first
        return TaskVerdict.UNDECIDED
    if all(score == 1.0 for score in scores):
        return TaskVerdict.SATURATED_HIGH
    if all(score == 0.0 for score in scores):
        return TaskVerdict.SATURATED_LOW
    if max(scores) - min(scores) >= DISCRIMINATION_THRESHOLD:
        return TaskVerdict.DISCRIMINATES
    return TaskVerdict.UNDECIDED


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.fmean(present) if present else None


def aggregate(
    samples: Sequence[EvaluationSample],
    *,
    run_id: str,
    label: str,
    phase: str,
    ran_at: datetime,
    harness_ref: str,
    caveats: Sequence[str] = (),
    note: str = "",
) -> EvaluationReport:
    """Reduce a run's samples to the report the platform stores.

    Every definition here mirrors `scripts/model-eval/analyse.py`, which is the
    reading already published in `docs/PROGRESS.md`, so the screen and the
    command-line report cannot disagree about what a number means:

    - a model's score is the mean over its **scored** samples, not over all of
      them, so a sample that returned no result lowers `scored_samples` rather
      than the score;
    - a task's score is the mean of that model's samples on it;
    - wall clock is summed within a round and reported as the range across
      rounds, because one round is one pass over the whole set;
    - the generation rate and the prompt depth are means over the samples that
      reported them, and they are carried together.

    Raises `ValueError` on an empty sequence: a run with no samples is an
    import that read the wrong file, and storing it would put an empty table on
    a screen that would then be indistinguishable from a run where every model
    failed.
    """
    if not samples:
        raise ValueError("an evaluation run needs at least one sample")

    model_refs = sorted({sample.model_ref for sample in samples})

    # Bucketed in one pass rather than re-scanned per cell. The grid is models
    # by tasks, so filtering the whole sample list inside a double loop is
    # O(models x tasks x samples): at a hundred models and a hundred tasks that
    # is seconds of arithmetic on an input a caller chooses the size of, in a
    # process that serves every other admin request.
    by_model: dict[str, list[EvaluationSample]] = {}
    by_model_task: dict[tuple[str, str], list[EvaluationSample]] = {}
    # Task order follows first appearance rather than the alphabet: the harness
    # emits them in the order the set is meant to be read, and groups A-H mean
    # something in that order.
    task_order: list[tuple[str, str]] = []
    seen_tasks: set[str] = set()
    for sample in samples:
        by_model.setdefault(sample.model_ref, []).append(sample)
        by_model_task.setdefault((sample.model_ref, sample.task), []).append(sample)
        if sample.task not in seen_tasks:
            seen_tasks.add(sample.task)
            task_order.append((sample.task, sample.group))

    tasks: list[EvaluationTaskScore] = []
    for model_ref in model_refs:
        for task, group in task_order:
            of_task = by_model_task.get((model_ref, task), [])
            scored = [sample.score for sample in of_task if sample.score is not None]
            tasks.append(
                EvaluationTaskScore(
                    model_ref=model_ref,
                    task=task,
                    group=group,
                    score=_mean(scored),
                    samples=len(scored),
                )
            )

    models: list[EvaluationModelScore] = []
    for model_ref in model_refs:
        of_model = by_model[model_ref]
        answered = [sample for sample in of_model if sample.score is not None]
        per_round: dict[int, float] = {}
        for sample in of_model:
            if sample.wall_seconds is not None:
                per_round[sample.round_index] = (
                    per_round.get(sample.round_index, 0.0) + sample.wall_seconds
                )
        depth = _mean([sample.prompt_tokens for sample in of_model])
        models.append(
            EvaluationModelScore(
                model_ref=model_ref,
                score=_mean([sample.score for sample in answered]),
                scored_samples=len(answered),
                no_result_samples=len(of_model) - len(answered),
                generation_tokens_per_second=_mean(
                    [sample.generation_tokens_per_second for sample in of_model]
                ),
                prompt_depth_tokens=int(depth) if depth is not None else None,
                seconds_per_round_min=min(per_round.values()) if per_round else None,
                seconds_per_round_max=max(per_round.values()) if per_round else None,
            )
        )

    return EvaluationReport(
        run=EvaluationRun(
            id=run_id,
            label=label,
            phase=phase,
            ran_at=ran_at,
            harness_ref=harness_ref,
            sample_count=len(samples),
            caveats=tuple(caveats),
            note=note,
        ),
        models=tuple(models),
        tasks=tuple(tasks),
    )
