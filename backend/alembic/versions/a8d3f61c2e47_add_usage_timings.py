"""add the runtime's timings to usage records

Revision ID: a8d3f61c2e47
Revises: e9c4b7a52d18
Create Date: 2026-10-11

PR7 on #24 (#53): prefill, decode and load time from the runtime's `done`,
so a slow request can be told apart from a cold load or a lost prefix cache.
Nullable with no backfill: no earlier row recorded them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8d3f61c2e47"
down_revision: str | None = "e9c4b7a52d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("prompt_eval_ms", "eval_ms", "load_ms")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("usage_records", sa.Column(column, sa.Integer, nullable=True))


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("usage_records", column)
