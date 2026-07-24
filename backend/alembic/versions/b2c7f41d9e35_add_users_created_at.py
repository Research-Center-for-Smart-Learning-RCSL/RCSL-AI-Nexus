"""add users.created_at

Revision ID: b2c7f41d9e35
Revises: 6ab1a0eec2d1
Create Date: 2026-07-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c7f41d9e35"
down_revision: str | None = "6ab1a0eec2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with a server default, so existing rows get a value and the
    # application never has to decide what "created" means for a row it did not
    # write. The default stays on the column afterwards: the creation time is
    # the database's to assign, not a client's clock.
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "created_at")
