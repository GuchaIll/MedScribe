"""Add tsvector GIN indexes for hybrid retrieval sparse search.

Creates GIN indexes on chunk_embeddings.chunk_text and
clinical_embeddings.fact_key to support PostgreSQL full-text search
(tsvector/tsquery) used by the HybridRetrievalService.

Revision ID: 002_tsvector_gin
Revises: 001_embeddings
Create Date: 2025-01-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "002_tsvector_gin"
down_revision: Union[str, None] = "001_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create GIN indexes for full-text search on embedding tables."""

    # ── GIN index on chunk_embeddings.chunk_text ─────────────────────────
    # Used by HybridRetrievalService._sparse_chunk_search() and
    # _sparse_patient_chunk_search() for tsvector/tsquery matching.
    op.execute(text(
        "CREATE INDEX idx_chk_chunk_text_gin ON chunk_embeddings "
        "USING gin (to_tsvector('english', chunk_text))"
    ))

    # ── GIN index on clinical_embeddings.fact_key ────────────────────────
    # Used by HybridRetrievalService._sparse_fact_search() for
    # keyword-based clinical fact retrieval.
    op.execute(text(
        "CREATE INDEX idx_ce_fact_key_gin ON clinical_embeddings "
        "USING gin (to_tsvector('english', fact_key))"
    ))


def downgrade() -> None:
    """Drop GIN indexes for full-text search."""
    op.execute(text("DROP INDEX IF EXISTS idx_chk_chunk_text_gin"))
    op.execute(text("DROP INDEX IF EXISTS idx_ce_fact_key_gin"))
