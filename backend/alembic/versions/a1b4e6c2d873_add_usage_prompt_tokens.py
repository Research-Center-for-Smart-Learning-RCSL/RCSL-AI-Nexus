"""add usage_records.prompt_tokens

Revision ID: a1b4e6c2d873
Revises: f7a9d24c8b16
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b4e6c2d873"
down_revision: str | None = "f7a9d24c8b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `NOT NULL DEFAULT 0`, and zero is the true value for every existing row
    # rather than a convenient filler: nothing read Ollama's `prompt_eval_count`
    # until this revision, so no prompt token has ever been counted. A nullable
    # column would have said "unknown", which is a different and worse claim to
    # hand to a quota query — `sum()` over nulls silently under-charges, which
    # is the behaviour being fixed.
    #
    # Deliberately a second column rather than a widening of `tokens`. Folding
    # the two together would reinterpret every historical row as a total it
    # never was, and an OpenAI client reads the two figures separately anyway.
    op.add_column(
        "usage_records",
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "prompt_tokens")
