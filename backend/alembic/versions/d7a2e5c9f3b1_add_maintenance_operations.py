"""add maintenance operations and their node steps

Revision ID: d7a2e5c9f3b1
Revises: c4f1a8e2d6b9
Create Date: 2026-10-25

#61 P4: what an entry does to each node, written by the admin's maintenance
coordinator as it goes, so a coordinator that restarts resumes rather than
repeats. Empty on deployment; nothing reads it until an entry is made.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d7a2e5c9f3b1"
down_revision: str | None = "c4f1a8e2d6b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_operations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("owner", sa.String(32), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('enter')", name="ck_maintenance_operations_kind"),
        sa.CheckConstraint(
            "status IN ('running', 'failed', 'succeeded', 'abandoned')",
            name="ck_maintenance_operations_status",
        ),
        sa.UniqueConstraint("kind", "epoch", name="uq_maintenance_operations_kind_epoch"),
    )
    op.create_table(
        "maintenance_node_steps",
        sa.Column(
            "operation_id",
            sa.String(32),
            sa.ForeignKey("maintenance_operations.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "node_id",
            sa.String(36),
            sa.ForeignKey("nodes.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interrupt", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_error", sa.Text(), nullable=True),
        sa.Column("reset_id", sa.String(32), nullable=True),
        sa.Column("reset", postgresql.JSONB(), nullable=True),
        sa.Column("accounting", sa.String(16), nullable=True),
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "phase IN ('pending', 'interrupted', 'snapshotted', 'reset', 'verified')",
            name="ck_maintenance_node_steps_phase",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'failed', 'done')", name="ck_maintenance_node_steps_status"
        ),
        sa.CheckConstraint(
            "accounting IS NULL OR accounting IN ('resolved', 'unresolved')",
            name="ck_maintenance_node_steps_accounting",
        ),
    )


def downgrade() -> None:
    op.drop_table("maintenance_node_steps")
    op.drop_table("maintenance_operations")
