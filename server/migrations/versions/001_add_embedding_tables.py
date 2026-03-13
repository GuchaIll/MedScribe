"""Add clinical_embeddings and chunk_embeddings tables with pgvector support.

Revision ID: 001_embeddings
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "001_embeddings"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    """Create pgvector extension and embedding tables."""

    # ── Enable pgvector extension ────────────────────────────────────────
    op.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # ── clinical_embeddings ──────────────────────────────────────────────
    op.create_table(
        "clinical_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("patient_id", sa.String(50), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("session_id", sa.String(50), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("record_id", sa.String(50), sa.ForeignKey("medical_records.id"), nullable=True),
        sa.Column(
            "fact_type", sa.String(50), nullable=False,
            comment="allergy, medication, diagnosis, vital, lab_result, procedure, problem",
        ),
        sa.Column(
            "fact_key", sa.String(200), nullable=False,
            comment="Canonical key, e.g. 'penicillin' for an allergy",
        ),
        sa.Column("fact_data", sa.JSON(), nullable=False, comment="Full structured fact"),
        # embedding column added via raw SQL below (vector type not in SA core)
        sa.Column("source_span", sa.Text(), nullable=True, comment="Original transcript span"),
        sa.Column("grounding_score", sa.Float(), nullable=True, comment="Cosine sim score"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5", comment="Extraction confidence"),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default="false", comment="Reviewed/high-confidence"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Add vector column via raw SQL (vector type not in SA core)
    op.execute(text(f"ALTER TABLE clinical_embeddings ADD COLUMN embedding vector({EMBEDDING_DIM}) NOT NULL"))

    # Indexes
    op.create_index("idx_ce_patient_type", "clinical_embeddings", ["patient_id", "fact_type"])
    op.create_index("idx_ce_session", "clinical_embeddings", ["session_id"])
    op.create_index("idx_ce_is_final", "clinical_embeddings", ["is_final"])
    op.create_index("idx_ce_patient_id", "clinical_embeddings", ["patient_id"])
    op.create_index("idx_ce_record_id", "clinical_embeddings", ["record_id"])

    # IVFFlat index for cosine distance search on clinical embeddings
    op.execute(text(
        "CREATE INDEX idx_ce_embedding_cosine ON clinical_embeddings "
        f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
    ))

    # ── chunk_embeddings ─────────────────────────────────────────────────
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(50), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "chunk_id", sa.String(100), nullable=False,
            comment="Matches ChunkArtifact.chunk_id",
        ),
        sa.Column("source_type", sa.String(20), nullable=False, comment="transcript or document"),
        sa.Column("chunk_text", sa.Text(), nullable=False, comment="Original chunk text"),
        sa.Column("start_time", sa.Float(), nullable=True, comment="Segment start time (seconds)"),
        sa.Column("end_time", sa.Float(), nullable=True, comment="Segment end time (seconds)"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Add vector column via raw SQL
    op.execute(text(f"ALTER TABLE chunk_embeddings ADD COLUMN embedding vector({EMBEDDING_DIM}) NOT NULL"))

    # Indexes
    op.create_index("idx_chk_session", "chunk_embeddings", ["session_id"])
    op.create_index("idx_chk_chunk_id", "chunk_embeddings", ["chunk_id"])

    # IVFFlat index for cosine distance search on chunk embeddings
    op.execute(text(
        "CREATE INDEX idx_chk_embedding_cosine ON chunk_embeddings "
        f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
    ))


def downgrade() -> None:
    """Drop embedding tables (pgvector extension kept)."""
    op.drop_table("chunk_embeddings")
    op.drop_table("clinical_embeddings")
    # Note: We intentionally do NOT drop the vector extension
    # as other tables/users may depend on it.
