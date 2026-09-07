"""add prompt_logs.compaction_tier

Revision ID: a2f7c31b9e84
Revises: c1d5f8a3e497
Create Date: 2026-09-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2f7c31b9e84"
down_revision: str | None = "c1d5f8a3e497"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A transcript records the prompt the model was *sent*. After a compaction
    # that is not the prompt the caller composed, and this table is the one
    # place in the platform where a person reads the prompt itself — so without
    # this column the reduced prompt would be the least visible place the
    # reduction went unannounced. See automatic-context-compaction.md §3.
    #
    # Nullable with no default, like the usage columns in c1d5f8a3e497: null
    # means nothing was compacted, which is the honest value for every existing
    # row and for most future ones.
    op.add_column(
        "prompt_logs",
        sa.Column("compaction_tier", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prompt_logs", "compaction_tier")
