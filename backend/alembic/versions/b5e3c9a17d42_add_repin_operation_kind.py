"""add the repin operation kind

Revision ID: b5e3c9a17d42
Revises: a4d81c6e9f27
Create Date: 2026-10-22

#68 §3: an operator's retry of the weights pin a pull could not set. It runs
on the node agent as a lifecycle operation, exclusive with dispatch like a pull,
so it is recorded like one.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b5e3c9a17d42"
down_revision: str | None = "a4d81c6e9f27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "('inference', 'embedding_batch', 'summary', 'load', 'unload', 'pull')"
_AFTER = "('inference', 'embedding_batch', 'summary', 'load', 'unload', 'pull', 'repin')"


def upgrade() -> None:
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint("ck_node_operations_kind", "node_operations", f"kind IN {_AFTER}")


def downgrade() -> None:
    # A repin stores no result, but the rows still have to go before the
    # constraint can narrow again.
    op.execute(
        "DELETE FROM attempt_results r USING node_operations o "
        "WHERE r.node_id = o.node_id AND r.op_id = o.op_id AND o.kind = 'repin'"
    )
    op.execute("DELETE FROM node_operations WHERE kind = 'repin'")
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint("ck_node_operations_kind", "node_operations", f"kind IN {_BEFORE}")
