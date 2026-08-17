"""What a capability evaluation measured, and what it is not entitled to say.

A run of `scripts/model-eval/` produces one score per model per task per round.
This module is the shape those samples are reduced to before anything reads
them: a run, a row per model, a row per model and task, and the caveats that
have to travel with the numbers.

**The caveats are data, not prose on a page.** A run's own record says things
the table cannot: which tasks carried no signal, how few the spread rests on,
whether it is comparable with the run before it. A screen that showed the
scores without those sentences would be showing a ranking the run does not
support, and a page that carried them as hardcoded copy would keep asserting
them about the *next* run, whose limits are different ones. So they are stored
against the run that earned them and rendered from it -- the same rule
`host-numbers-explainer` follows for the figures it explains.

Deliberately no counts in this docstring, for the reason the rule exists. An
earlier version quoted "eleven of eighteen carry no signal" from the
2026-08-15 entry, which is that day's `full`-phase reading; the stored run is
`full` with `repair` superseding it, and `verdicts()` computes thirteen. A
comment that restates a figure the module derives is a second source of truth
for it.

**Nothing here is a live measurement.** A run is a record of one execution on
one day against one set of models; the platform does not re-run it and cannot
tell whether it still describes what is deployed. `ran_at` is therefore a field
rather than a detail, and the read path carries it into every response.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

DISCRIMINATION_THRESHOLD = 0.15
"""How far apart the best and worst model must score before a task is credited
with telling them apart.

The value `scripts/model-eval/analyse.py` uses, and it is duplicated here
deliberately rather than imported: that script is a developer tool outside the
application image, and a number the platform renders a verdict from has to be
in the platform. `test_evaluation_aggregate.py` reads the literal back out of
that script and asserts it equals this constant, so the copy cannot drift
silently -- a claim this docstring made from the day it was written and which
nothing did until 2026-08-17.
"""


class TaskVerdict(StrEnum):
    """What one task did to the field of models in a run.

    The distinction the evaluation's own design rests on: a task every
    candidate passes and a task every candidate fails both produce a tidy
    column and neither separates anybody. Naming them is what stops a reader
    counting eighteen tasks and believing eighteen of them contributed.
    """

    DISCRIMINATES = "discriminates"
    """The spread across models reached `DISCRIMINATION_THRESHOLD`. These are
    the tasks the run's verdict actually rests on."""

    SATURATED_HIGH = "saturated_high"
    """Every model scored 1.00. Carries no signal, and is replaceable under
    section 4.4 of the evaluation design."""

    SATURATED_LOW = "saturated_low"
    """Every model scored 0.00 -- which is a finding about the task or about
    the whole field, never about one model. `insufficient_data` is the example
    that matters: all three candidates invented a confident number rather than
    reporting that the data did not determine one."""

    UNDECIDED = "undecided"
    """Scored, but neither saturated nor separating. A real result that simply
    does not carry the comparison."""


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    """One model's attempt at one task in one round.

    The unit the harness writes and the only unit that was measured. Everything
    else in this module is derived from a sequence of these, so a figure on the
    screen can always be traced to a set of samples rather than to a step that
    happened between the run and the reader.
    """

    model_ref: str
    task: str
    group: str
    round_index: int
    score: float | None
    """None where the sample returned no result at all -- a truncated response
    with no final answer, a load failure. Deliberately not zero: a candidate
    that produced nothing and a candidate that answered wrongly are different
    findings, and averaging them together is the defect the harness's own
    report separates them to avoid."""

    generation_tokens_per_second: float | None = None
    prompt_tokens: int | None = None
    wall_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class EvaluationModelScore:
    """One model's whole result in one run."""

    model_ref: str
    score: float | None
    """Mean over scored samples, 0..1. None when nothing scored."""

    scored_samples: int
    no_result_samples: int
    generation_tokens_per_second: float | None
    prompt_depth_tokens: int | None
    """The mean measured prompt depth. Carried beside the generation rate
    because a rate without a depth cannot be compared with another one -- the
    rule the harness states and the reason two of this project's earlier
    comparisons had to be withdrawn."""

    seconds_per_round_min: float | None
    seconds_per_round_max: float | None
    """Wall clock for one full pass over the task set, as a range across
    rounds. The more useful figure than the token rate: a model with the higher
    rate can still take longer, because it writes more."""


@dataclass(frozen=True, slots=True)
class EvaluationTaskScore:
    """One model's mean on one task, and how many samples it rests on."""

    model_ref: str
    task: str
    group: str
    score: float | None
    samples: int


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """One execution of the task set: what ran, when, and against what."""

    id: str
    label: str
    """How an operator refers to this run. Unique, and the handle re-importing
    replaces on, so correcting a run does not leave two of it."""

    phase: str
    """The harness's own phase name (`pilot` calibrates the set, `full`
    compares the candidates). Kept because a calibration read and a comparison
    read answer different questions and their numbers must not be mixed."""

    ran_at: datetime
    harness_ref: str
    """Where the harness that produced this lives, as a path or a commit. The
    2026-08-14 run is uncomparable with anything precisely because its harness
    was never committed, so this field is the one that makes a run citable."""

    sample_count: int
    caveats: tuple[str, ...]
    """What this run does not establish, in the words of whoever ran it."""

    note: str = ""
    imported_at: datetime | None = None
    imported_by: str | None = None
    """Display name of whoever loaded it, stored denormalised like the audit
    log's, so the row stays readable after the account is gone."""


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """A run with everything derived from its samples.

    One aggregate rather than three lists a caller assembles, because the
    verdicts below are a property of the *set* of models in the run: computing
    them needs every model's task scores at once, and a caller holding two of
    the three lists could compute a verdict that is quietly wrong.
    """

    run: EvaluationRun
    models: tuple[EvaluationModelScore, ...]
    tasks: tuple[EvaluationTaskScore, ...]

    @property
    def model_refs(self) -> tuple[str, ...]:
        return tuple(model.model_ref for model in self.models)

    def verdicts(self) -> Mapping[str, TaskVerdict]:
        """What each task did to this field of models.

        Computed on read rather than stored, so the rule lives in one place and
        a stored verdict cannot survive a change to the threshold that produced
        it. See `TaskVerdict` for what each value means.
        """
        by_task: dict[str, list[float]] = {}
        for entry in self.tasks:
            if entry.score is not None:
                by_task.setdefault(entry.task, []).append(entry.score)
        return MappingProxyType({task: _verdict_for(scores) for task, scores in by_task.items()})


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
