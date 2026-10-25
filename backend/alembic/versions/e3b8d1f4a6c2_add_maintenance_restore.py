"""add the maintenance restore

Revision ID: e3b8d1f4a6c2
Revises: d7a2e5c9f3b1
Create Date: 2026-10-25

#61 P5: a restore is a maintenance operation of its own, its node steps pass
through `loaded` and `probed` before `verified`, and the node agent records
the bounded functional check it runs on each restored model as a `probe`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3b8d1f4a6c2"
down_revision: str | None = "d7a2e5c9f3b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = "('inference', 'embedding_batch', 'summary', 'load', 'unload', 'pull', 'repin')"
_KINDS_AFTER = (
    "('inference', 'embedding_batch', 'summary', 'load', 'unload', 'pull', 'repin', 'probe')"
)
_PHASES_BEFORE = "('pending', 'interrupted', 'snapshotted', 'reset', 'verified')"
_PHASES_AFTER = "('pending', 'interrupted', 'snapshotted', 'reset', 'loaded', 'probed', 'verified')"


def upgrade() -> None:
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint(
        "ck_node_operations_kind", "node_operations", f"kind IN {_KINDS_AFTER}"
    )
    op.drop_constraint("ck_maintenance_operations_kind", "maintenance_operations", type_="check")
    op.create_check_constraint(
        "ck_maintenance_operations_kind", "maintenance_operations", "kind IN ('enter', 'restore')"
    )
    op.drop_constraint("ck_maintenance_node_steps_phase", "maintenance_node_steps", type_="check")
    op.create_check_constraint(
        "ck_maintenance_node_steps_phase", "maintenance_node_steps", f"phase IN {_PHASES_AFTER}"
    )


def downgrade() -> None:
    # The audit rows stay: they reference no row, and they are evidence.
    op.execute("DELETE FROM node_operations WHERE kind = 'probe'")
    op.execute(
        "DELETE FROM maintenance_node_steps s USING maintenance_operations o "
        "WHERE s.operation_id = o.id AND o.kind = 'restore'"
    )
    op.execute("DELETE FROM maintenance_operations WHERE kind = 'restore'")
    op.drop_constraint("ck_maintenance_node_steps_phase", "maintenance_node_steps", type_="check")
    op.create_check_constraint(
        "ck_maintenance_node_steps_phase", "maintenance_node_steps", f"phase IN {_PHASES_BEFORE}"
    )
    op.drop_constraint("ck_maintenance_operations_kind", "maintenance_operations", type_="check")
    op.create_check_constraint(
        "ck_maintenance_operations_kind", "maintenance_operations", "kind IN ('enter')"
    )
    op.drop_constraint("ck_node_operations_kind", "node_operations", type_="check")
    op.create_check_constraint(
        "ck_node_operations_kind", "node_operations", f"kind IN {_KINDS_BEFORE}"
    )
