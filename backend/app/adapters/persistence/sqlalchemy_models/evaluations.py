"""Persistence evaluations boundary."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EvaluationRunRow(Base):
    """One execution of the capability task set.

    Platform-global like `models` and `nodes`, and for the same reason: it
    describes the fleet rather than anyone's content, so it carries no
    `tenant_id`. Every tenant that can see the models can see what they scored.
    """

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), unique=True)
    """Unique, and that is what makes re-importing a correction rather than a
    duplicate. A run gets re-imported — the 2026-08-15 figures were themselves
    corrected after three prompts were found to be measuring their own
    formatting — and two rows of the same run on one screen is the failure this
    constraint exists to prevent."""

    phase: Mapped[str] = mapped_column(String(32))
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    """Indexed because the only ordering this table is ever read in is newest
    first, and "what is the current reading" is the question the screen opens
    with."""

    harness_ref: Mapped[str] = mapped_column(String(255), default="")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    caveats: Mapped[list[str]] = mapped_column(JSON, default=list)
    """What the run does not establish. JSON rather than a `Text` blob so the
    screen renders them as the list they are, and stored per run rather than
    written into the page, because the next run's caveats are different ones."""

    note: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    imported_by: Mapped[str] = mapped_column(String(255), default="")
    """Display name, denormalised for the reason `retention_policies` stores
    one: the row outlives the account."""


class EvaluationModelScoreRow(Base):
    """One model's whole result in one run."""

    __tablename__ = "evaluation_model_scores"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    """Wider than the 36 a UUID needs, because it is not one: the writer builds
    it as `<run id>:m<index>` so that ordering by id is ordering by the
    aggregate's own sequence. A plain UUID would need a sort column beside it
    that means the same thing."""
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    """Cascading, unlike most foreign keys here. These rows are derived from
    the run and mean nothing without it, so deleting a run must not be able to
    leave scores behind that no screen can reach and no query will find."""

    model_ref: Mapped[str] = mapped_column(String(128))
    """The runtime reference the harness ran (`qwen3.6:35b-a3b-q8_0`), not a
    registry alias. An alias is a name an operator may reassign to different
    weights; what was measured was the weights."""

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_samples: Mapped[int] = mapped_column(Integer, default=0)
    no_result_samples: Mapped[int] = mapped_column(Integer, default=0)
    generation_tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_depth_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seconds_per_round_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    seconds_per_round_max: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvaluationTaskScoreRow(Base):
    """One model's mean on one task, which is where the verdicts come from."""

    __tablename__ = "evaluation_task_scores"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    """`<run id>:t<index>`, zero-padded, for the reason above."""
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    model_ref: Mapped[str] = mapped_column(String(128))
    task: Mapped[str] = mapped_column(String(64))
    task_group: Mapped[str] = mapped_column(String(8))
    """The harness's group letter. Named `task_group` rather than `group`
    because the bare word is reserved in SQL: SQLAlchemy quotes it, and the
    first hand-written query against this table would not."""

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # The read is always "every task score for this run", assembled into a
        # grid, so the run is the filter and the pair below is the sort.
        Index("ix_evaluation_task_scores_run_task", "run_id", "task", "model_ref"),
    )


class EvaluationTaskDefinitionRow(Base):
    """The text of one task, as the run that stored it asked it.

    Per run rather than per task in a table of its own, and that duplication is
    deliberate. Prompts are revised between phases -- `vm_trace`'s was shortened
    between `hard-pilot` and `hard-full` on 2026-09-03 -- so a shared row would
    make every earlier run silently claim to have asked the current question.
    The harness's file cannot stand in for it either: the admin image does not
    carry `scripts/`.
    """

    __tablename__ = "evaluation_task_definitions"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    """`<run id>:d<index>`, zero-padded, for the reason above."""
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    """Cascading like the score rows, and for the same reason: the text is
    derived from the run and means nothing without it, so a deleted run must not
    leave prompts behind that no screen can reach and no query will find."""

    task: Mapped[str] = mapped_column(String(64))
    task_group: Mapped[str] = mapped_column(String(8))
    """`task_group`, not `group`, for the reason `EvaluationTaskScoreRow` gives:
    the bare word is reserved in SQL and only stays harmless while every reader
    quotes it."""

    kind: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text, default="")
    """`Text` rather than a bounded `String`, because the bound would have to be
    guessed: the dialogue tasks carry a system prompt plus a whole student
    script, and a truncated question beside a score is worse than none."""

    checks: Mapped[int] = mapped_column(Integer, default=0)
