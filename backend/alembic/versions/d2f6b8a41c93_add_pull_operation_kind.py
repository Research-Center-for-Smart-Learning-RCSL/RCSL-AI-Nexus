"""add the pull operation kind

Revision ID: d2f6b8a41c93
Revises: c4e1a9d07b52
Create Date: 2026-10-09

PR4b on #24: a model download becomes a lifecycle operation of the node
agent, exclusive with dispatch on its node (design S5), so it is recorded like
`load` and `unload`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d2f6b8a41c93"
down_revision: str | None = "c4e1a9d07b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "('inference', 'embedding_batch', 'summary', 'load', 'unload')"
_AFTER = "('inference', 'embedding_batch', 'summary', 'load', 'unload', 'pull')"


def upgrade() -> None:
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint("ck_node_operations_kind", "node_operations", f"kind IN {_AFTER}")


def downgrade() -> None:
    # The step below this one drops `node_operations` altogether, so removing
    # the pull rows first loses nothing that downgrade would have kept.
    op.execute(
        "DELETE FROM attempt_results r USING node_operations o "
        "WHERE r.node_id = o.node_id AND r.op_id = o.op_id AND o.kind = 'pull'"
    )
    op.execute("DELETE FROM node_operations WHERE kind = 'pull'")
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint("ck_node_operations_kind", "node_operations", f"kind IN {_BEFORE}")
