"""add the node's observed runtime version

Revision ID: e9c4b7a52d18
Revises: d2f6b8a41c93
Create Date: 2026-10-09

PR2b on #24: a validated counting profile is keyed by the runtime's version,
which the heartbeat observes through the node's agent and stamps here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9c4b7a52d18"
down_revision: str | None = "d2f6b8a41c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("runtime_version", sa.String(64), nullable=True))
    op.add_column(
        "nodes", sa.Column("runtime_version_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("nodes", "runtime_version_at")
    op.drop_column("nodes", "runtime_version")
