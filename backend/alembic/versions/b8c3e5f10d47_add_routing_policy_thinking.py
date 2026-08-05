"""add routing_policies.thinking

Revision ID: b8c3e5f10d47
Revises: a1b2c3d4e5f6
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c3e5f10d47"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no server default, which is the whole point of the column:
    # NULL means "this policy expresses no preference, take the deployment
    # default", and that is exactly what every existing row means. A NOT NULL
    # column with a default would have had to pick a value for policies whose
    # authors never considered the question, and would then have overridden the
    # deployment setting they were in fact relying on.
    op.add_column("routing_policies", sa.Column("thinking", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("routing_policies", "thinking")
