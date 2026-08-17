"""add refusals.actor_display

Revision ID: f3c8a15d27be
Revises: e7b41c9d0a26
Create Date: 2026-08-18

Denormalised like `audit_log.actor_display`, and for the same reason `refusals`
carries no foreign keys: the row has to stay readable after the account it
names is gone. It also answers "whose 413s are these?" for a reader holding
`refusal:read_all` — without it, a page of other people's refusals is a column
of uuids and a lookup per row.

**Its own revision rather than an edit to `e7b41c9d0a26`, which was written the
same day and is still uncommitted.** That one has already run against the
deployment and against three real rows. Amending an applied revision leaves the
machine that ran it without the column while a fresh clone gets one, which is
the divergence between what is written down and what is in force that this
repository keeps finding the hard way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c8a15d27be"
down_revision: str | None = "e7b41c9d0a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `server_default=""` rather than nullable: the rows already stored were
    # written before anything knew a display name, and empty is what they
    # honestly hold. The mapper reads that back as "unknown" instead of
    # inventing one, and the screen shows the account id it does have.
    op.add_column(
        "refusals",
        sa.Column("actor_display", sa.String(255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("refusals", "actor_display")
