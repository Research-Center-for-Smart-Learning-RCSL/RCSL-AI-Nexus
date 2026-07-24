"""add api_keys.created_at

Revision ID: c93a17b64ef2
Revises: b2c7f41d9e35
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c93a17b64ef2"
down_revision: str | None = "b2c7f41d9e35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No `last_used_at` alongside it. Maintaining one would put a write to this
    # table on the gateway's hot path, and the least-privilege split in
    # security.md section 6 is meant to deny the gateway exactly that. The same
    # fact comes from `usage_records`, which the gateway does write and which
    # is already indexed on (api_key_id, at).
    op.add_column(
        "api_keys",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "created_at")
