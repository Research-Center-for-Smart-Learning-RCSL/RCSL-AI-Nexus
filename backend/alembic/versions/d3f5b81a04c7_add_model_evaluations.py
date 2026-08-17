"""add model evaluations

Three tables behind the evaluation screen: a run, a row per model in it, and a
row per model and task. Platform-global like `models` and `nodes` — an
evaluation describes the fleet rather than a tenant's content, so none of them
carries a `tenant_id`.

The children cascade from the run. They are derived rows that mean nothing
without it, so a deleted run must not be able to leave scores behind that no
screen can reach and no query will find; that is the one place in this schema
where `ondelete` is the right answer rather than the convenient one.

Revision ID: d3f5b81a04c7
Revises: a1d6e93c7f52
Create Date: 2026-08-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3f5b81a04c7"
down_revision: str | None = "a1d6e93c7f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        # Unique, which is what makes a re-import a correction rather than a
        # duplicate. The published 2026-08-15 figures are themselves a
        # correction of that day's first reading, so this is the expected case
        # and not a corner.
        sa.Column("label", sa.String(128), nullable=False, unique=True),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("harness_ref", sa.String(255), nullable=False, server_default=""),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        # What the run does not establish, stored with it. JSON rather than
        # Text so the screen renders the list as a list, and per run rather
        # than in the page's copy, because the next run's caveats are different
        # ones and a page asserting these about it would be wrong.
        sa.Column("caveats", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("imported_by", sa.String(255), nullable=False, server_default=""),
    )
    # The only ordering this table is read in is newest first, and "what is the
    # current reading" is the question the screen opens with.
    op.create_index("ix_evaluation_runs_ran_at", "evaluation_runs", ["ran_at"])

    op.create_table(
        "evaluation_model_scores",
        # Wider than a UUID because it is not one: the writer builds it as
        # `<run id>:m<index>`, so ordering by id is ordering by the aggregate's
        # own sequence rather than by a sort column that has to be kept in step.
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The runtime reference the harness ran, not a registry alias: an alias
        # is a name an operator may point at different weights, and what was
        # measured was the weights.
        sa.Column("model_ref", sa.String(128), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("scored_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_result_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation_tokens_per_second", sa.Float(), nullable=True),
        sa.Column("prompt_depth_tokens", sa.Integer(), nullable=True),
        sa.Column("seconds_per_round_min", sa.Float(), nullable=True),
        sa.Column("seconds_per_round_max", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_evaluation_model_scores_run_id", "evaluation_model_scores", ["run_id"]
    )

    op.create_table(
        "evaluation_task_scores",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_ref", sa.String(128), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        # `task_group`, not `group`: the harness calls it a group, but the
        # bare word is reserved in SQL and only stays harmless while every
        # reader quotes it. The first hand-written query would not.
        sa.Column("task_group", sa.String(8), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_evaluation_task_scores_run_id", "evaluation_task_scores", ["run_id"]
    )
    # The read is always "every task score for this run", assembled into a
    # grid, so the run is the filter and the pair is the sort.
    op.create_index(
        "ix_evaluation_task_scores_run_task",
        "evaluation_task_scores",
        ["run_id", "task", "model_ref"],
    )


def downgrade() -> None:
    # Reversible without argument, unlike the `prompt_logs` drop: what is lost
    # is a record of a measurement that still exists in `scripts/model-eval/`
    # and in the progress log, and can be imported again.
    op.drop_index("ix_evaluation_task_scores_run_task", table_name="evaluation_task_scores")
    op.drop_index("ix_evaluation_task_scores_run_id", table_name="evaluation_task_scores")
    op.drop_table("evaluation_task_scores")
    op.drop_index("ix_evaluation_model_scores_run_id", table_name="evaluation_model_scores")
    op.drop_table("evaluation_model_scores")
    op.drop_index("ix_evaluation_runs_ran_at", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
