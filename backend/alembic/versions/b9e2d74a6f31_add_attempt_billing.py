"""store billing snapshots per request attempt

Revision ID: b9e2d74a6f31
Revises: a8d3f61c2e47
Create Date: 2026-10-14

An unsent retry may route to another model or run on another day (#32).
Keep each new attempt's snapshot immutable. NULL identifies legacy attempts
and old gateways during rollout; readers fall back to the original binding.
Historical attempt-specific facts cannot be reconstructed, so no backfill
claims to correct them and existing usage rows are left alone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b9e2d74a6f31"
down_revision: str | None = "a8d3f61c2e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("request_attempts", sa.Column("billing", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("request_attempts", "billing")
