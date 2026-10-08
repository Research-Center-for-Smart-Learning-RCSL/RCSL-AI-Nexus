"""add node agent tables

Revision ID: c4e1a9d07b52
Revises: b8d3e5f12a47
Create Date: 2026-10-09

PR4a-1 of the final spec on #24 (design revisions 1-5 there). The node agent
is the only sender to its runtime; these tables are what it owns and what the
gateway binds requests to. Nothing reads them yet: the agent lands idle and the
gateway wiring (PR4a-2) is behind `NODE_AGENT_ENABLED`, off by default.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4e1a9d07b52"
down_revision: str | None = "b8d3e5f12a47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "('inference', 'embedding_batch', 'summary', 'load', 'unload')"
_STATES = "('accepted', 'running', 'completed', 'failed', 'outcome_unknown', 'cancelled_unsent')"
_TOTALS_SOURCES = "('runtime_final', 'estimated_from_chunks', 'unavailable')"
_PROMPT_BASES = "('runtime_final', 'exact_counter', 'estimate')"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    # Where a node's agent is reached, and the lock domain bound to it on its
    # first claim (design S2: immutable once set, so another volume or VM
    # cannot take the node over after a session loss).
    op.add_column("nodes", sa.Column("agent_url", sa.String(255), nullable=True))
    op.add_column("nodes", sa.Column("lock_domain_id", sa.String(64), nullable=True))
    # The expected manifest SHA-256 (design S5). A weights pin, distinct from
    # residency intent; null means unpinned.
    op.add_column("models", sa.Column("manifest_digest", sa.String(64), nullable=True))

    op.create_table(
        "node_agents",
        sa.Column(
            "node_id", sa.String(36), sa.ForeignKey("nodes.id"), primary_key=True, nullable=False
        ),
        sa.Column("generation", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("boot_id", sa.String(36), nullable=True),
        sa.Column("kernel_boot_id", sa.String(64), nullable=True),
        sa.Column("election_backend_pid", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "node_operations",
        sa.Column("node_id", sa.String(36), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("op_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        # Who sent it, never rewritten, apart from whose writes count now
        # (design R2): takeover moves `owner_generation` and nothing else of
        # the sender's provenance.
        sa.Column("origin_generation", sa.BigInteger, nullable=False),
        sa.Column("origin_boot_id", sa.String(36), nullable=False),
        sa.Column("owner_generation", sa.BigInteger, nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("payload_hash", sa.String(80), nullable=True),
        sa.Column("store_output", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()
        ),
        sa.Column("running_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(32), nullable=True),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Checkpointed observations while a stream runs (design T3, U2):
        # chunk counts and elapsed time, never called tokens.
        sa.Column("observed", postgresql.JSONB, nullable=True),
        # Terminal figures: raw runtime totals, finish reason, failure code.
        sa.Column("terminal", postgresql.JSONB, nullable=True),
        sa.Column("replay_unavailable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("node_id", "op_id"),
        sa.CheckConstraint(f"kind IN {_KINDS}", name="ck_node_operations_kind"),
        sa.CheckConstraint(f"state IN {_STATES}", name="ck_node_operations_state"),
    )
    # The node-wide block is one indexed EXISTS per promotion.
    op.create_index(
        "ix_node_operations_unknown",
        "node_operations",
        ["node_id"],
        postgresql_where=sa.text("state = 'outcome_unknown'"),
    )
    op.create_index(
        "ix_node_operations_open",
        "node_operations",
        ["node_id", "state"],
        postgresql_where=sa.text("state IN ('accepted', 'running')"),
    )

    op.create_table(
        "attempt_results",
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("op_id", sa.String(36), nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("node_id", "op_id"),
        sa.ForeignKeyConstraint(
            ["node_id", "op_id"], ["node_operations.node_id", "node_operations.op_id"]
        ),
    )

    # Stale completions, resolutions and takeovers: evidence that must
    # outlive the rows it is about.
    op.create_table(
        "node_operation_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("op_id", sa.String(36), nullable=True),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index("ix_node_operation_audit_node_at", "node_operation_audit", ["node_id", "at"])

    # Global request identity (final spec §5, design S6): the current binding,
    # versioned so concurrent rebinds converge by conditional update ...
    op.create_table(
        "request_bindings",
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("current_seq", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(80), nullable=False),
        sa.Column("hash_version", sa.String(16), nullable=False),
        sa.Column("key_supplied", sa.Boolean, nullable=False),
        sa.Column("billing", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("tenant_id", "request_id"),
    )
    # ... and the immutable history of every attempt it has pointed at.
    op.create_table(
        "request_attempts",
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("op_id", sa.String(36), nullable=False),
        sa.Column("retry_of_seq", sa.Integer, nullable=True),
        sa.Column("client_delivery_complete", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("tenant_id", "request_id", "seq"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["request_bindings.tenant_id", "request_bindings.request_id"],
        ),
        # An attempt's identity is its op id, a UUID minted by the gateway and
        # unique platform-wide; `usage_records.attempt_id` holds that same
        # value. Unique here so that no reconciliation keyed by it can ever
        # reach another attempt (review on #24, revision 6).
        sa.UniqueConstraint("op_id", name="uq_request_attempts_op_id"),
    )

    # Exactly-once usage per attempt, and where its figures came from
    # (design R6, T3, U2). `completed` keeps its meaning: the client received
    # the whole response; `runtime_completed` is the runtime reaching `done`.
    op.add_column("usage_records", sa.Column("attempt_id", sa.String(36), nullable=True))
    op.add_column("usage_records", sa.Column("totals_source", sa.String(32), nullable=True))
    op.add_column("usage_records", sa.Column("prompt_tokens_basis", sa.String(16), nullable=True))
    op.add_column("usage_records", sa.Column("runtime_completed", sa.Boolean, nullable=True))
    op.create_index("uq_usage_records_attempt_id", "usage_records", ["attempt_id"], unique=True)
    op.create_check_constraint(
        "ck_usage_records_totals_source",
        "usage_records",
        f"totals_source IS NULL OR totals_source IN {_TOTALS_SOURCES}",
    )
    op.create_check_constraint(
        "ck_usage_records_prompt_tokens_basis",
        "usage_records",
        f"prompt_tokens_basis IS NULL OR prompt_tokens_basis IN {_PROMPT_BASES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_usage_records_prompt_tokens_basis", "usage_records", type_="check")
    op.drop_constraint("ck_usage_records_totals_source", "usage_records", type_="check")
    op.drop_index("uq_usage_records_attempt_id", table_name="usage_records")
    for column in ("runtime_completed", "prompt_tokens_basis", "totals_source", "attempt_id"):
        op.drop_column("usage_records", column)
    op.drop_table("request_attempts")
    op.drop_table("request_bindings")
    op.drop_index("ix_node_operation_audit_node_at", table_name="node_operation_audit")
    op.drop_table("node_operation_audit")
    op.drop_table("attempt_results")
    op.drop_index("ix_node_operations_open", table_name="node_operations")
    op.drop_index("ix_node_operations_unknown", table_name="node_operations")
    op.drop_table("node_operations")
    op.drop_table("node_agents")
    op.drop_column("models", "manifest_digest")
    op.drop_column("nodes", "lock_domain_id")
    op.drop_column("nodes", "agent_url")
