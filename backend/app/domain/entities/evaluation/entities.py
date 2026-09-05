"""Evaluation entities and value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

DISCRIMINATION_THRESHOLD = 0.15


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
class EvaluationTaskDefinition:
    """The text of one task, as the run actually asked it.

    Stored with the run rather than read back out of the harness, and the
    distinction is not pedantry: task prompts are revised between phases --
    `vm_trace`'s was shortened between `hard-pilot` and `hard-full` on
    2026-09-03 -- so a screen that paired a stored run with today's
    `scripts/model-eval/` would put a question beside a score that was never
    the answer to it. The admin container does not carry `scripts/` either, so
    the alternative is not merely wrong, it is unavailable.
    """

    task: str
    group: str
    kind: str
    """`code`, `exact` or `dialogue`. Carried because it is what tells a reader
    why a task has eleven checks and its neighbour has one, and a percentage
    without that is a number the screen cannot explain."""

    prompt: str
    """The full text the model was given. For a dialogue task that is the
    system prompt and the whole student script: rendering only the system half
    would show the rules while hiding every attempt to break them, which is the
    half the score is about."""

    checks: int
    """How many independent scoring units the task's score is a mean over. A
    0.5 on a two-check task and a 0.5 on a twelve-check one are different
    findings, and the screen can only say so if the count travels with the
    text."""


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

    task_definitions: tuple[EvaluationTaskDefinition, ...] = ()
    """The text of the tasks this run asked, where the importer was given it.

    Defaulted to empty rather than required, because two runs are already
    stored without definitions and a field that broke their rendering would be
    a schema change presented as a feature. A screen with no definitions shows
    the scores it has always shown; one with them shows the question beside
    them. Neither case is an error, and nothing here treats an empty tuple as
    one."""

    @property
    def model_refs(self) -> tuple[str, ...]:
        return tuple(model.model_ref for model in self.models)

    def verdicts(self) -> Mapping[str, TaskVerdict]:
        """What each task did to this field of models.

        Computed on read rather than stored, so the rule lives in one place and
        a stored verdict cannot survive a change to the threshold that produced
        it. See `TaskVerdict` for what each value means.
        """
        from .scoring import _verdict_for

        by_task: dict[str, list[float]] = {}
        for entry in self.tasks:
            if entry.score is not None:
                by_task.setdefault(entry.task, []).append(entry.score)
        return MappingProxyType({task: _verdict_for(scores) for task, scores in by_task.items()})
