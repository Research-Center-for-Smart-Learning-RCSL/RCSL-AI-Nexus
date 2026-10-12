"""Shared knowledge fences and pinned vector-space identity.

Revision ID: f2c7d9e40b31
Revises: f1b6c8d39a20
"""

import sqlalchemy as sa

from alembic import op

revision = "f2c7d9e40b31"
down_revision = "f1b6c8d39a20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_tenant_epochs",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mutations_in_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_identity", sa.String(1024), nullable=True),
        sa.Column(
            "index_requires_rebuild", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.CheckConstraint(
            "epoch >= 0 AND mutations_in_progress >= 0", name="ck_knowledge_tenant_epoch"
        ),
    )
    # Untyped legacy vectors cannot be adopted from today's routing policy:
    # equal dimensions provide no proof that their embedding spaces agree.
    op.execute("""
        INSERT INTO knowledge_tenant_epochs (tenant_id, index_requires_rebuild)
        SELECT t.id, EXISTS (SELECT 1 FROM knowledge_documents d WHERE d.tenant_id = t.id)
        FROM tenants t
    """)
    op.add_column(
        "knowledge_collections",
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_collections",
        sa.Column("mutations_in_progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_knowledge_collection_epoch",
        "knowledge_collections",
        "epoch >= 0 AND mutations_in_progress >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_knowledge_collection_epoch", "knowledge_collections", type_="check")
    op.drop_column("knowledge_collections", "mutations_in_progress")
    op.drop_column("knowledge_collections", "epoch")
    op.drop_table("knowledge_tenant_epochs")
