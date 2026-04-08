"""Make sessions.patient_id nullable for Go gateway compatibility.

The Go API gateway creates sessions before the patient is identified.
The patient_id is associated later during pipeline trigger. This matches
the Python SessionService behavior which only persists to DB when
patient_id is non-empty.

Revision ID: 003_nullable_session_patient
Revises: 002_tsvector_gin
Create Date: 2026-04-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "003_nullable_session_patient"
down_revision: Union[str, None] = "002_tsvector_gin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "patient_id",
        existing_type=sa.String(50),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill any NULLs before restoring NOT NULL to avoid constraint error.
    op.execute("UPDATE sessions SET patient_id = '' WHERE patient_id IS NULL")
    op.alter_column(
        "sessions",
        "patient_id",
        existing_type=sa.String(50),
        nullable=False,
    )
