"""add platform_snapshots

Revision ID: b8d3e5f12a47
Revises: a2f7c31b9e84
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d3e5f12a47"
down_revision: str | None = "a2f7c31b9e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("models_loaded", sa.Integer, nullable=False),
        sa.Column("models_total", sa.Integer, nullable=False),
        sa.Column("nodes_online", sa.Integer, nullable=False),
        sa.Column("nodes_total", sa.Integer, nullable=False),
        sa.Column("api_keys_active", sa.Integer, nullable=False),
        sa.Column("users_total", sa.Integer, nullable=False),
    )
    op.create_index(
        "ix_platform_snapshots_at",
        "platform_snapshots",
        ["at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_platform_snapshots_at", table_name="platform_snapshots")
    op.drop_table("platform_snapshots")
