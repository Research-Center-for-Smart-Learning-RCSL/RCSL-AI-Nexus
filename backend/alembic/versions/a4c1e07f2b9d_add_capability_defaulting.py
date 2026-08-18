"""add api_keys.default_capability and usage_records.requested_capability

Revision ID: a4c1e07f2b9d
Revises: f3c8a15d27be
Create Date: 2026-08-18

The opt-in half of the answer to a question three integrations have now asked:
a client that sends a model name rather than a capability is refused, and the
refusal is the only thing that tells anybody their picker overrode the model
line they configured. Making the gateway guess for everyone would buy the
convenience by making that misconfiguration permanent and invisible. A key may
name its own substitute instead, and only its own — see
`domain/entities/api_key.py`.

**Two columns, and the second is what makes the first defensible.** Turning the
setting on removes the refusal, so the evidence has to survive somewhere that
is neither a response header the caller may not read nor a log line that
rotates. `usage_records.requested_capability` keeps what was actually asked
for, so "is this key being defaulted, and what is its client sending?" stays a
query after the fact.

Both nullable with no server default, because null is not a migration artefact
in either case: on `api_keys` it is the behaviour every existing key should
keep and the one this platform goes on issuing by default, and on
`usage_records` it means the caller asked for what it got — true of every row
already stored.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c1e07f2b9d"
down_revision: str | None = "f3c8a15d27be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("default_capability", sa.String(64), nullable=True),
    )
    op.add_column(
        "usage_records",
        sa.Column("requested_capability", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "requested_capability")
    op.drop_column("api_keys", "default_capability")
