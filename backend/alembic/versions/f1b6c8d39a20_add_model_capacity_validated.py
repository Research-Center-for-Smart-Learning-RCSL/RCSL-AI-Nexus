"""Track whether a model's declared context has actually been read.

Revision ID: f1b6c8d39a20
Revises: b9e2d74a6f31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1b6c8d39a20"
down_revision: str | None = "b9e2d74a6f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column("capacity_validated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("models", "capacity_validated")
