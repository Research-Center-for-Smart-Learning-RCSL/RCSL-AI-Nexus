"""Admin evaluations schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.evaluation import (
    EvaluationModelScore,
    EvaluationReport,
    EvaluationRun,
    EvaluationTaskScore,
)

MAX_EVALUATION_SAMPLES = 20_000


class EvaluationRunResponse(BaseModel):
    """One stored run, without its scores. What the run list is made of."""

    id: str
    label: str
    phase: str
    ran_at: datetime
    harness_ref: str
    sample_count: int
    caveats: list[str]
    """What this run does not establish. Carried in the response rather than
    written into the screen, because the next run's caveats are different ones
    and a page asserting these about it would be wrong."""

    note: str
    imported_at: datetime | None
    imported_by: str | None

    @classmethod
    def of(cls, run: EvaluationRun) -> EvaluationRunResponse:
        return cls(
            id=run.id,
            label=run.label,
            phase=run.phase,
            ran_at=run.ran_at,
            harness_ref=run.harness_ref,
            sample_count=run.sample_count,
            caveats=list(run.caveats),
            note=run.note,
            imported_at=run.imported_at,
            imported_by=run.imported_by,
        )


class EvaluationModelScoreResponse(BaseModel):
    model_ref: str
    score: float | None
    scored_samples: int
    no_result_samples: int
    generation_tokens_per_second: float | None
    prompt_depth_tokens: int | None
    seconds_per_round_min: float | None
    seconds_per_round_max: float | None

    model_config = ConfigDict(protected_namespaces=())
    """`model_ref` collides with pydantic's own `model_` namespace, which warns
    rather than fails and would keep warning on every import. The field is named
    for what it holds — the runtime reference of a language model — and renaming
    it to satisfy a framework prefix would make the API read worse than the
    warning does."""

    @classmethod
    def of(cls, score: EvaluationModelScore) -> EvaluationModelScoreResponse:
        return cls(
            model_ref=score.model_ref,
            score=score.score,
            scored_samples=score.scored_samples,
            no_result_samples=score.no_result_samples,
            generation_tokens_per_second=score.generation_tokens_per_second,
            prompt_depth_tokens=score.prompt_depth_tokens,
            seconds_per_round_min=score.seconds_per_round_min,
            seconds_per_round_max=score.seconds_per_round_max,
        )


class EvaluationTaskScoreResponse(BaseModel):
    model_ref: str
    task: str
    group: str
    score: float | None
    samples: int

    model_config = ConfigDict(protected_namespaces=())

    @classmethod
    def of(cls, score: EvaluationTaskScore) -> EvaluationTaskScoreResponse:
        return cls(
            model_ref=score.model_ref,
            task=score.task,
            group=score.group,
            score=score.score,
            samples=score.samples,
        )


class EvaluationReportResponse(BaseModel):
    """A run and everything derived from its samples.

    `verdicts` is computed rather than stored (see `EvaluationReport.verdicts`)
    and is carried here rather than left to the client, for the reason it is
    computed in the aggregate at all: it is a property of the whole field of
    models, and a screen deriving it from the rows it happens to have rendered
    would get it wrong the moment a filter existed.
    """

    run: EvaluationRunResponse
    models: list[EvaluationModelScoreResponse]
    tasks: list[EvaluationTaskScoreResponse]
    verdicts: dict[str, str]

    @classmethod
    def of(cls, report: EvaluationReport) -> EvaluationReportResponse:
        return cls(
            run=EvaluationRunResponse.of(report.run),
            models=[EvaluationModelScoreResponse.of(s) for s in report.models],
            tasks=[EvaluationTaskScoreResponse.of(s) for s in report.tasks],
            verdicts={task: verdict.value for task, verdict in report.verdicts().items()},
        )


class EvaluationSampleRequest(BaseModel):
    """One model's attempt at one task in one round, as the harness wrote it."""

    model_ref: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=64)
    group: str = Field(default="", max_length=8)
    round_index: int = Field(ge=0)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Null where the sample returned no result at all. Distinct from zero, and
    the API keeps the distinction because averaging the two together is the
    defect the harness's own report separates them to avoid."""

    generation_tokens_per_second: float | None = Field(default=None, ge=0.0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    wall_seconds: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(protected_namespaces=())


class ImportEvaluationRequest(BaseModel):
    """A whole run, as samples rather than as scores.

    **The caller sends what was measured and the platform does the arithmetic.**
    Accepting pre-computed scores would let two importers disagree about what a
    score means — mean over scored samples or over all of them, one figure the
    harness's report and the screen would then quietly differ on — and there
    would be nothing in the stored row to say which had been used.
    """

    label: str = Field(min_length=1, max_length=128)
    phase: str = Field(default="full", max_length=32)
    ran_at: datetime
    harness_ref: str = Field(default="", max_length=255)
    caveats: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=8192)
    samples: list[EvaluationSampleRequest] = Field(min_length=1, max_length=MAX_EVALUATION_SAMPLES)
    """At least one: a run with no samples is an import that read the wrong
    file, and an empty table on this screen is indistinguishable from a run
    where every model failed.

    And a ceiling, because reducing samples is arithmetic a caller chooses the
    size of, in a process that serves every other admin request. The bound is
    generous against real runs -- the sixteen-task set is 280 lines -- and the
    body-size limit alone was not one: at 40 MiB it admits several hundred
    thousand minimal sample objects."""
