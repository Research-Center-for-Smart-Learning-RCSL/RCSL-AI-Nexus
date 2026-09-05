"""add evaluation task definitions

The text of the tasks a run asked, stored with the run. Platform-global like
the three tables it joins, for the same reason: it describes the fleet's
measurement rather than a tenant's content, so it carries no `tenant_id`.

Per run rather than a shared table of tasks, and the duplication is the point.
Prompts are revised between phases — `vm_trace`'s was shortened between
`hard-pilot` and `hard-full` on 2026-09-03 — so one row shared across runs
would make every earlier run silently claim to have asked today's question.
Reading `scripts/model-eval/` at render time is not an alternative either: the
admin image does not carry `scripts/`, so the text has to travel with the run
or not exist.

Cascading from the run, like the score tables and for the reason stated there:
these are derived rows that mean nothing without it, and a deleted run must not
leave prompts behind that no screen can reach and no query will find.

Revision ID: b7e2c94f1a63
Revises: a4c1e07f2b9d
Create Date: 2026-09-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e2c94f1a63"
down_revision: str | None = "a4c1e07f2b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_task_definitions",
        # Wider than a UUID because it is not one: the writer builds it as
        # `<run id>:d<index>`, zero-padded, so ordering by id is ordering by
        # the aggregate's own sequence rather than by a sort column that has to
        # be kept in step.
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task", sa.String(64), nullable=False),
        # `task_group`, not `group`, for the reason `evaluation_task_scores`
        # gives: the bare word is reserved in SQL and only stays harmless while
        # every reader quotes it. The first hand-written query would not.
        sa.Column("task_group", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        # Text rather than a bounded String, because the bound would have to be
        # guessed: a dialogue task is a system prompt plus a whole student
        # script, and a truncated question beside a score is worse than none.
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("checks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_evaluation_task_definitions_run_id",
        "evaluation_task_definitions",
        ["run_id"],
    )


def downgrade() -> None:
    # Reversible on the same argument the table it joins was: what is lost is a
    # copy of text that still exists in `scripts/model-eval/` and can be
    # imported again — with the caveat this table exists to record, that the
    # file today may no longer be the file the run was measured against.
    op.drop_index(
        "ix_evaluation_task_definitions_run_id",
        table_name="evaluation_task_definitions",
    )
    op.drop_table("evaluation_task_definitions")
