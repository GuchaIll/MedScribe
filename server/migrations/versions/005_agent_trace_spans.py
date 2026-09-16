"""Create agent_trace_spans table for agent runtime tracing (#48).

Stores one row per TraceSpan emitted by the agent runtime.  PHI rules
apply: no utterance text, prompts, completions, or tool payloads in
production rows.  Retention policy defined in §16 Q17.

Revision ID: 005_agent_trace_spans
Revises: 004_provenance_receipt_locators
Create Date: 2026-09-16 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_agent_trace_spans"
down_revision: Union[str, None] = "004_provenance_receipt_locators"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_trace_spans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_schema_version", sa.String(length=20), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=32), nullable=False),
        sa.Column("parent_span_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("span_id"),
    )
    op.create_index("idx_ats_trace_id", "agent_trace_spans", ["trace_id"])
    op.create_index("idx_ats_session_id", "agent_trace_spans", ["session_id"])
    op.create_index("idx_ats_started_at", "agent_trace_spans", ["started_at"])
    op.create_index("idx_ats_parent_span_id", "agent_trace_spans", ["parent_span_id"])


def downgrade() -> None:
    op.drop_index("idx_ats_parent_span_id", table_name="agent_trace_spans")
    op.drop_index("idx_ats_started_at", table_name="agent_trace_spans")
    op.drop_index("idx_ats_session_id", table_name="agent_trace_spans")
    op.drop_index("idx_ats_trace_id", table_name="agent_trace_spans")
    op.drop_table("agent_trace_spans")
