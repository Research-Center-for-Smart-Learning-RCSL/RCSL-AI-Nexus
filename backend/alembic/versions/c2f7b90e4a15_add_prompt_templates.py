"""add prompt_templates

Revision ID: c2f7b90e4a15
Revises: b8c3e5f10d47
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2f7b90e4a15"
down_revision: str | None = "b8c3e5f10d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        # Tenant data, like the knowledge base and unlike models or nodes: a
        # template is text a team wrote and can encode how they work.
        sa.Column(
            "tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False, server_default=""),
        # Text rather than a bounded String: the length limit belongs in the
        # domain (MAX_SYSTEM_PROMPT_CHARS), where it can be refused with a
        # message naming the limit, rather than in the column, where exceeding
        # it is a database error the caller cannot act on.
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Per tenant, not global. The name is what a caller writes in
    # `"prompt_template": "..."`, so it has to be unique where that request is
    # resolved and no wider: a global constraint would refuse a name because
    # another tenant had taken it, which both blocks an ordinary choice and
    # reports that the other tenant exists.
    op.create_index(
        "ix_prompt_templates_tenant_name", "prompt_templates", ["tenant_id", "name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_templates_tenant_name", table_name="prompt_templates")
    op.drop_table("prompt_templates")
