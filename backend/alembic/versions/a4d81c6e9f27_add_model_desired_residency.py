"""Residency intent, separate from lifecycle state (#49 §1).

Every row starts with no intent (`desired_resident = false`, version 0); the
first operator Load records it. Not backfilled from `state = 'loaded'`: models
have been unloaded outside the registry, so a row can still say `loaded` for
weights nobody wants resident, and enabling `RESIDENCY_RECONCILER_ENABLED`
would then reload them without anyone asking.

Revision ID: a4d81c6e9f27
Revises: f2c7d9e40b31
"""

import sqlalchemy as sa

from alembic import op

revision = "a4d81c6e9f27"
down_revision = "f2c7d9e40b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column("desired_resident", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "models",
        sa.Column("desired_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint("ck_models_desired_version", "models", "desired_version >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_models_desired_version", "models", type_="check")
    op.drop_column("models", "desired_version")
    op.drop_column("models", "desired_resident")
