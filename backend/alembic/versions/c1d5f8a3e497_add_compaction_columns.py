"""add api_keys.compaction_enabled and usage_records compaction columns

Revision ID: c1d5f8a3e497
Revises: b7e2c94f1a63
Create Date: 2026-09-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d5f8a3e497"
down_revision: str | None = "b7e2c94f1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Default on: the plan (automatic-context-compaction.md §5.5) says the
    # migration turns it on for every key that already exists, which is a
    # behaviour change to live integrations — so it ships together with the
    # disclosure, never before it.
    op.add_column(
        "api_keys",
        sa.Column(
            "compaction_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Nullable with no default: null means "no compaction happened on this
    # request", which is the honest starting value for every existing row and
    # most future ones.
    op.add_column(
        "usage_records",
        sa.Column("compaction_tier", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "usage_records",
        sa.Column("tokens_before_compaction", sa.Integer(), nullable=True),
    )
    op.add_column(
        "usage_records",
        sa.Column("tokens_after_compaction", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "tokens_after_compaction")
    op.drop_column("usage_records", "tokens_before_compaction")
    op.drop_column("usage_records", "compaction_tier")
    op.drop_column("api_keys", "compaction_enabled")
