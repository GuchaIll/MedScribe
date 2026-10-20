"""Per-fact chunk provenance, span locators, observed_at, received_at (Phase 1B #53).

Adds to chunk_embeddings: document_id, page, received_at, received_at_is_legacy.
Adds to clinical_embeddings: source_chunk_ids, received_at, received_at_is_legacy.
Legacy rows: received_at back-filled from created_at, received_at_is_legacy = true.

Revision ID: 004_provenance_receipt_locators
Revises: 003_nullable_session_patient
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "004_provenance_receipt_locators"
down_revision: Union[str, None] = "003_nullable_session_patient"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── chunk_embeddings ──────────────────────────────────────────────────────
    op.add_column(
        "chunk_embeddings",
        sa.Column("document_id", sa.String(100), nullable=True, comment="Source document id for document chunks"),
    )
    op.add_column(
        "chunk_embeddings",
        sa.Column("page", sa.Integer(), nullable=True, comment="Page number within source document; null for transcript chunks"),
    )
    op.add_column(
        "chunk_embeddings",
        sa.Column(
            "received_at",
            sa.DateTime(),
            nullable=True,
            comment="When the system received the source material; null = legacy row",
        ),
    )
    op.add_column(
        "chunk_embeddings",
        sa.Column(
            "received_at_is_legacy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True when received_at was back-filled from created_at",
        ),
    )
    op.create_index("idx_chk_document_id", "chunk_embeddings", ["document_id"])

    # Back-fill legacy rows: received_at = created_at, received_at_is_legacy = true
    op.execute(
        "UPDATE chunk_embeddings SET received_at = created_at, received_at_is_legacy = true "
        "WHERE received_at IS NULL"
    )

    # ── clinical_embeddings ───────────────────────────────────────────────────
    op.add_column(
        "clinical_embeddings",
        sa.Column(
            "source_chunk_ids",
            postgresql.ARRAY(sa.String()),
            nullable=True,
            comment="Chunk ids that produced this fact",
        ),
    )
    op.add_column(
        "clinical_embeddings",
        sa.Column(
            "received_at",
            sa.DateTime(),
            nullable=True,
            comment="When the system received the source material; null = legacy row",
        ),
    )
    op.add_column(
        "clinical_embeddings",
        sa.Column(
            "received_at_is_legacy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True when received_at was back-filled from created_at",
        ),
    )

    # Back-fill legacy rows
    op.execute(
        "UPDATE clinical_embeddings SET received_at = created_at, received_at_is_legacy = true "
        "WHERE received_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("idx_chk_document_id", table_name="chunk_embeddings")
    op.drop_column("chunk_embeddings", "received_at_is_legacy")
    op.drop_column("chunk_embeddings", "received_at")
    op.drop_column("chunk_embeddings", "page")
    op.drop_column("chunk_embeddings", "document_id")

    op.drop_column("clinical_embeddings", "received_at_is_legacy")
    op.drop_column("clinical_embeddings", "received_at")
    op.drop_column("clinical_embeddings", "source_chunk_ids")
