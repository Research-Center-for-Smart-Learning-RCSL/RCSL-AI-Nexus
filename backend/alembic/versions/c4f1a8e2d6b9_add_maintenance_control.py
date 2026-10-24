"""add the maintenance hold

Revision ID: c4f1a8e2d6b9
Revises: b5e3c9a17d42
Create Date: 2026-10-24

#61: one row every process reads to decide whether the platform serves. Seeded
open at epoch 0, which is also the epoch every session issued before this
migration decodes to, so deploying it revokes nobody.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f1a8e2d6b9"
down_revision: str | None = "b5e3c9a17d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_control",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("admission_closed", sa.Boolean(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("expected_return_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_by", sa.String(36), nullable=True),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_maintenance_control_singleton"),
        sa.CheckConstraint(
            "phase IN ('normal', 'maintenance')", name="ck_maintenance_control_phase"
        ),
        sa.CheckConstraint("epoch >= 0", name="ck_maintenance_control_epoch"),
    )
    op.execute(
        "INSERT INTO maintenance_control (id, admission_closed, phase, epoch, revision) "
        "VALUES (1, false, 'normal', 0, 0)"
    )


def downgrade() -> None:
    op.drop_table("maintenance_control")
