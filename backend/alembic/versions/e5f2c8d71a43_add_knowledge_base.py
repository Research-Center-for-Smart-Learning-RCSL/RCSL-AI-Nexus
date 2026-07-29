"""add knowledge base collections and documents

Revision ID: e5f2c8d71a43
Revises: d4e8f1a2b6c9
Create Date: 2026-07-29

The knowledge base (security.md section 7.3), plugged into the tenant boundary
the previous migration built. Both tables carry `tenant_id` with a foreign key,
because a collection and a document are tenant data in the way `models` and
`nodes` are not: they hold the team's unpublished research, the highest
sensitivity class in section 9.1.

The document's tenant is stored on the document rather than reached through its
collection, so a scoped read of `knowledge_documents` needs no join to be
correctly scoped.

No column holds document content or a filesystem path. The bytes and the
extracted text live on a mounted volume under keys derived from `id`; the
uploader's filename is kept for display only. See
adapters/storage/filesystem_documents.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f2c8d71a43"
down_revision: str | None = "d4e8f1a2b6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_collections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", name="fk_knowledge_collections_tenant_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_knowledge_collections_tenant_id", "knowledge_collections", ["tenant_id"])
    # Unique per tenant rather than globally: two tenants naming a collection
    # "Papers" is ordinary, and a global constraint would leak that another
    # tenant had taken the name.
    op.create_index(
        "ix_knowledge_collections_tenant_name",
        "knowledge_collections",
        ["tenant_id", "name"],
        unique=True,
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", name="fk_knowledge_documents_tenant_id"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            sa.String(length=36),
            sa.ForeignKey("knowledge_collections.id", name="fk_knowledge_documents_collection_id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("uploaded_by", sa.String(length=36), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
    op.create_index(
        "ix_knowledge_documents_collection_id", "knowledge_documents", ["collection_id"]
    )
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_collection_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_tenant_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_collections_tenant_name", table_name="knowledge_collections")
    op.drop_index("ix_knowledge_collections_tenant_id", table_name="knowledge_collections")
    op.drop_table("knowledge_collections")
