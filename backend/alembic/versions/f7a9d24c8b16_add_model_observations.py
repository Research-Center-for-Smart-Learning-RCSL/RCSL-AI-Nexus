"""add models observed_state, observed_memory_gb, observed_at

Revision ID: f7a9d24c8b16
Revises: e5f2c8d71a43
Create Date: 2026-07-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a9d24c8b16"
down_revision: str | None = "e5f2c8d71a43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All three nullable with no default: null is the honest starting value,
    # meaning "the heartbeat has not observed this model yet". Backfilling
    # from `state` would assert an observation nobody made, which is the exact
    # lie these columns exist to end.
    op.add_column("models", sa.Column("observed_state", sa.String(24), nullable=True))
    op.add_column("models", sa.Column("observed_memory_gb", sa.Float(), nullable=True))
    op.add_column("models", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("models", "observed_at")
    op.drop_column("models", "observed_memory_gb")
    op.drop_column("models", "observed_state")
