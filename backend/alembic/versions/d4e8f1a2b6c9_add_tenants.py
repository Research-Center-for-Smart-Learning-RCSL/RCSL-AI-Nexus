"""add tenants and tenant_id columns

Revision ID: d4e8f1a2b6c9
Revises: c93a17b64ef2
Create Date: 2026-07-25

Multi-tenancy foundation (security.md section 7.3, ARCHITECTURE.md section 2.8).
Every tenant-scoped table gains a `tenant_id`; the tenant-scoped repositories
enforce the filter. Existing rows are backfilled into a single default tenant,
which is also where a fresh deployment bootstraps its first admin, so the column
can be made NOT NULL without a data migration window.

`models`, `nodes` and `routing_policies` deliberately gain nothing: they are the
shared compute the tenants use, not tenant data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e8f1a2b6c9"
down_revision: str | None = "c93a17b64ef2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = "default"
DEFAULT_TENANT_NAME = "Default"

# usage_records and audit_log carry the column but no foreign key, matching the
# existing choice to keep usage_records free of foreign keys (it must survive a
# key deletion). Integrity for those is maintained at the application layer,
# where the tenant is stamped from an already-authenticated actor. users and
# api_keys already reference other tables, so a tenant foreign key there is in
# keeping.
_FK_TABLES = ("users", "api_keys")
_COLUMN_ONLY_TABLES = ("usage_records", "audit_log")
_ALL_TABLES = _FK_TABLES + _COLUMN_ONLY_TABLES


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # The default tenant has to exist before the backfill can point at it and
    # before the NOT NULL and the foreign keys are added.
    op.execute(
        sa.text("INSERT INTO tenants (id, name) VALUES (:id, :name)").bindparams(
            id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME
        )
    )

    for table in _ALL_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(length=36), nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET tenant_id = :tid").bindparams(tid=DEFAULT_TENANT_ID)
        )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    for table in _FK_TABLES:
        op.create_foreign_key(
            f"fk_{table}_tenant_id", table, "tenants", ["tenant_id"], ["id"]
        )


def downgrade() -> None:
    for table in _FK_TABLES:
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
    for table in _ALL_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
    op.drop_table("tenants")
