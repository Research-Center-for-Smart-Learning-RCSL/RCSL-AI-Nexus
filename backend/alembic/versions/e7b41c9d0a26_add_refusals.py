"""add refusals

Revision ID: e7b41c9d0a26
Revises: d3f5b81a04c7
Create Date: 2026-08-18

Where a refused caller can read their own refusal back. Two people lost an
evening each on 2026-08-17 to refusals that were correct, permanent and silent
about which of several things they had just changed had caused them; nothing on
this platform stored a refusal at all, so answering "what happened at 19:16?"
meant an administrator reading container logs.

What lands here is what left the process — the code, the status, the message the
caller received and the caller-facing figures that came with it — and never
`detail`, which is operator-facing, nor the model's alias, which two error
classes are deliberately careful to withhold.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b41c9d0a26"
down_revision: str | None = "d3f5b81a04c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refusals",
        sa.Column("id", sa.String(36), primary_key=True),
        # No foreign key on tenant_id, actor_id or api_key_id, like `audit_log`
        # and `prompt_logs`: the row must outlive the account or key it names.
        # A refusal that vanished when its key was revoked would take the
        # evidence with the credential, and revoking a key is one of the things
        # somebody does *because* of a refusal.
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("api_key_id", sa.String(64), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("surface", sa.String(32), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        # Text on the path and the message for the reason `prompt_logs` gives:
        # `audit_log` used bounded columns and lost whole rows whose values were
        # wider, silently, so padding a URL suppressed the record of probing it
        # (PROGRESS.md 2026-08-02). A path is exactly such a value.
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("figures", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_refusals_tenant_id", "refusals", ["tenant_id"])
    op.create_index("ix_refusals_at", "refusals", ["at"])
    op.create_index("ix_refusals_actor_id", "refusals", ["actor_id"])
    op.create_index("ix_refusals_api_key_id", "refusals", ["api_key_id"])
    # What an operator filters by. A status is too coarse — the evening this
    # table exists for had two 413s with different causes and two 409s with
    # nothing in common.
    op.create_index("ix_refusals_code", "refusals", ["code"])
    # The way in: a caller reports a failure by quoting the request id from
    # their error envelope, and this is the table that turns it back into what
    # happened.
    op.create_index("ix_refusals_request_id", "refusals", ["request_id"])
    # The two paged reads, each carrying its filter and its sort together:
    # "this tenant's refusals, newest first" and "this account's".
    op.create_index("ix_refusals_tenant_at", "refusals", ["tenant_id", "at"])
    op.create_index("ix_refusals_actor_at", "refusals", ["actor_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_refusals_actor_at", table_name="refusals")
    op.drop_index("ix_refusals_tenant_at", table_name="refusals")
    op.drop_index("ix_refusals_request_id", table_name="refusals")
    op.drop_index("ix_refusals_code", table_name="refusals")
    op.drop_index("ix_refusals_api_key_id", table_name="refusals")
    op.drop_index("ix_refusals_actor_id", table_name="refusals")
    op.drop_index("ix_refusals_at", table_name="refusals")
    op.drop_index("ix_refusals_tenant_id", table_name="refusals")
    op.drop_table("refusals")
