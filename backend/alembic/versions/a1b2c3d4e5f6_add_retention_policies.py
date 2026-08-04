"""add retention_policies

Revision ID: a1b2c3d4e5f6
Revises: a1b4e6c2d873
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "a1b4e6c2d873"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No seed rows. An absent row means the default in
    # `domain/entities/retention.py`, so a dataset added later needs no
    # backfill, and the first row appears when somebody actually disagrees with
    # the default — which is also the first time there is an author worth
    # recording in `updated_by`. Seeding here would write a decision nobody
    # made under the name of whoever ran the migration.
    op.create_table(
        "retention_policies",
        sa.Column("dataset", sa.String(32), primary_key=True),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("retention_policies")
