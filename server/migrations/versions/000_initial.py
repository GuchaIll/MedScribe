"""Initial schema — creates all core application tables.

Revision ID: 000_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000

Tables created (in FK-safe order):
    users, patients, sessions, medical_records,
    audit_logs, workflow_checkpoints, documents
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "000_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create core application tables."""

    # ── Enum types (raw SQL — avoids SQLAlchemy DDL visitor double-creation) ──
    op.execute(text(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole') THEN "
        "    CREATE TYPE userrole AS ENUM ('doctor', 'nurse', 'admin', 'medical_assistant'); "
        "  END IF; "
        "END $$;"
    ))
    op.execute(text(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sessionstatus') THEN "
        "    CREATE TYPE sessionstatus AS ENUM ('active', 'completed', 'error', 'review_pending'); "
        "  END IF; "
        "END $$;"
    ))
    op.execute(text(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ocrstatus') THEN "
        "    CREATE TYPE ocrstatus AS ENUM ('pending', 'processing', 'completed', 'failed'); "
        "  END IF; "
        "END $$;"
    ))

    # ── users ────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # Apply the enum type via ALTER COLUMN after table creation
    op.execute(text("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole"))
    op.create_index("idx_users_username", "users", ["username"])
    op.create_index("idx_users_email", "users", ["email"])
    # ── patients ─────────────────────────────────────────────────────────
    op.create_table(
        "patients",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("mrn", sa.String(50), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("dob", sa.DateTime(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(20), nullable=True),
        sa.Column("encrypted_demographics", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(50), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("idx_patient_mrn", "patients", ["mrn"])
    op.create_index("idx_patient_name", "patients", ["full_name"])
    op.create_index("idx_patient_created_at", "patients", ["created_at"])

    # ── sessions ─────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("patient_id", sa.String(50), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("doctor_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("visit_type", sa.String(100), nullable=True),
        sa.Column("workflow_state", sa.JSON(), nullable=True),
        sa.Column("checkpoint_id", sa.String(100), nullable=True),
        sa.Column("audio_file_path", sa.String(500), nullable=True),
        sa.Column("transcription_file_path", sa.String(500), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.execute(text("ALTER TABLE sessions ALTER COLUMN status DROP DEFAULT"))
    op.execute(text("ALTER TABLE sessions ALTER COLUMN status TYPE sessionstatus USING status::sessionstatus"))
    op.execute(text("ALTER TABLE sessions ALTER COLUMN status SET DEFAULT 'active'::sessionstatus"))
    op.create_index("idx_session_patient", "sessions", ["patient_id"])
    op.create_index("idx_session_doctor", "sessions", ["doctor_id"])
    op.create_index("idx_session_status", "sessions", ["status"])
    op.create_index("idx_session_started_at", "sessions", ["started_at"])

    # ── medical_records ───────────────────────────────────────────────────
    op.create_table(
        "medical_records",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("patient_id", sa.String(50), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("session_id", sa.String(50), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("structured_data", sa.JSON(), nullable=False),
        sa.Column("clinical_suggestions", sa.JSON(), nullable=True),
        sa.Column("soap_note", sa.Text(), nullable=True),
        sa.Column("validation_report", sa.JSON(), nullable=True),
        sa.Column("conflict_report", sa.JSON(), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("record_type", sa.String(50), nullable=True),
        sa.Column("template_used", sa.String(100), nullable=True),
        sa.Column("created_by", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_by", sa.String(50), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("idx_record_patient", "medical_records", ["patient_id"])
    op.create_index("idx_record_session", "medical_records", ["session_id"])
    op.create_index("idx_record_created_at", "medical_records", ["created_at"])
    op.create_index("idx_record_is_final", "medical_records", ["is_final"])

    # ── audit_logs ────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_role", sa.String(50), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("idx_audit_user", "audit_logs", ["user_id"])
    op.create_index("idx_audit_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("idx_audit_timestamp", "audit_logs", ["timestamp"])
    op.create_index("idx_audit_action", "audit_logs", ["action"])

    # ── workflow_checkpoints ──────────────────────────────────────────────
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("session_id", sa.String(50), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("checkpoint_name", sa.String(100), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("state_data", sa.JSON(), nullable=False),
        sa.Column("is_resumable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("review_completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_checkpoint_session", "workflow_checkpoints", ["session_id"])
    op.create_index("idx_checkpoint_thread", "workflow_checkpoints", ["thread_id"])
    op.create_index("idx_checkpoint_needs_review", "workflow_checkpoints", ["needs_human_review"])

    # ── documents ─────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("session_id", sa.String(50), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("patient_id", sa.String(50), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("ocr_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("document_type", sa.String(50), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("structured_fields", sa.JSON(), nullable=True),
        sa.Column("confidence_map", sa.JSON(), nullable=True),
        sa.Column("conflicts", sa.JSON(), nullable=True),
        sa.Column("overall_confidence", sa.Float(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("field_count", sa.Integer(), nullable=True),
        sa.Column("conflict_count", sa.Integer(), nullable=True),
        sa.Column("processing_errors", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.execute(text("ALTER TABLE documents ALTER COLUMN ocr_status DROP DEFAULT"))
    op.execute(text("ALTER TABLE documents ALTER COLUMN ocr_status TYPE ocrstatus USING ocr_status::ocrstatus"))
    op.execute(text("ALTER TABLE documents ALTER COLUMN ocr_status SET DEFAULT 'pending'::ocrstatus"))
    op.create_index("idx_document_session", "documents", ["session_id"])
    op.create_index("idx_document_patient", "documents", ["patient_id"])
    op.create_index("idx_document_status", "documents", ["ocr_status"])
    op.create_index("idx_document_type", "documents", ["document_type"])


def downgrade() -> None:
    """Drop all core application tables and enum types."""
    op.drop_table("documents")
    op.drop_table("workflow_checkpoints")
    op.drop_table("audit_logs")
    op.drop_table("medical_records")
    op.drop_table("sessions")
    op.drop_table("patients")
    op.drop_table("users")

    op.execute(text("DROP TYPE IF EXISTS ocrstatus"))
    op.execute(text("DROP TYPE IF EXISTS sessionstatus"))
    op.execute(text("DROP TYPE IF EXISTS userrole"))
