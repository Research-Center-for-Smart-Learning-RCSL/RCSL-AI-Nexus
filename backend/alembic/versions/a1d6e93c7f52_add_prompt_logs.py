"""add prompt_logs

The table behind security.md section 9.2's full prompt and completion logging:
written only while a credential's debug window is open, retained for markedly
less time than anything else, and readable only under `prompt_log:read`.

Revision ID: a1d6e93c7f52
Revises: c2f7b90e4a15
Create Date: 2026-08-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1d6e93c7f52"
down_revision: str | None = "c2f7b90e4a15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        # No foreign key on tenant_id, actor_id or api_key_id, like `audit_log`
        # and for the same reason: the row must outlive the account or key it
        # names. A transcript that vanished when its key was revoked would take
        # the evidence with the credential.
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("api_key_id", sa.String(64), nullable=True),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("model_alias", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        # Text, not String(n), on all three. `audit_log` used bounded columns
        # and lost whole rows whose values were wider — silently, so padding a
        # URL suppressed the record of probing it (PROGRESS.md 2026-08-02). A
        # transcript is the widest value in this schema, so the same choice
        # here would drop precisely the rows somebody opened a window to read.
        # These are bounded by time (the retention sweep) and by a per-field
        # cap in the domain that records the fact of having applied.
        sa.Column("messages", sa.Text(), nullable=False),
        sa.Column("completion", sa.Text(), nullable=False, server_default=""),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("finish_reason", sa.String(32), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated_fields", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_prompt_logs_tenant_id", "prompt_logs", ["tenant_id"])
    op.create_index("ix_prompt_logs_at", "prompt_logs", ["at"])
    op.create_index("ix_prompt_logs_actor_id", "prompt_logs", ["actor_id"])
    op.create_index("ix_prompt_logs_api_key_id", "prompt_logs", ["api_key_id"])
    # The way in. A caller reports a failure by quoting the request id from
    # their error envelope, and finding that conversation is the reason the
    # window was opened in the first place.
    op.create_index("ix_prompt_logs_request_id", "prompt_logs", ["request_id"])
    # The paged read is "this tenant's transcripts, newest first", so the filter
    # and the sort belong in one index.
    op.create_index("ix_prompt_logs_tenant_at", "prompt_logs", ["tenant_id", "at"])


def downgrade() -> None:
    # Dropping the table destroys every transcript in it, which is the one
    # downgrade in this repository whose data loss is arguably the point: this
    # table exists only to hold the most sensitive text the platform sees, and
    # rolling the feature back should not leave that text behind in a schema
    # nothing reads any more.
    op.drop_index("ix_prompt_logs_tenant_at", table_name="prompt_logs")
    op.drop_index("ix_prompt_logs_request_id", table_name="prompt_logs")
    op.drop_index("ix_prompt_logs_api_key_id", table_name="prompt_logs")
    op.drop_index("ix_prompt_logs_actor_id", table_name="prompt_logs")
    op.drop_index("ix_prompt_logs_at", table_name="prompt_logs")
    op.drop_index("ix_prompt_logs_tenant_id", table_name="prompt_logs")
    op.drop_table("prompt_logs")
