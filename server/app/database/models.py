"""
SQLAlchemy models for the Medical Transcription application.
Defines the database schema for patients, sessions, records, and users.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
    Float,
    Boolean,
    JSON,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    Index
)
from sqlalchemy.orm import relationship
import enum

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback: pgvector not installed — define Vector as a no-op for import safety
    Vector = None

from app.database.base import Base


class UserRole(str, enum.Enum):
    """User roles for RBAC."""
    DOCTOR = "doctor"
    NURSE = "nurse"
    ADMIN = "admin"
    MEDICAL_ASSISTANT = "medical_assistant"


class SessionStatus(str, enum.Enum):
    """Session status states."""
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"
    REVIEW_PENDING = "review_pending"


class Patient(Base):
    """
    Patient demographic and profile information.
    Stores core patient data with relationships to sessions and records.
    """
    __tablename__ = "patients"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Core demographics
    mrn = Column(String(50), unique=True, nullable=False, index=True, comment="Medical Record Number")
    full_name = Column(String(200), nullable=False)
    dob = Column(DateTime, nullable=False, comment="Date of Birth")
    age = Column(Integer, nullable=True)
    sex = Column(String(20), nullable=True)

    # Encrypted PHI (Protected Health Information)
    # This field stores encrypted JSON with sensitive demographics
    encrypted_demographics = Column(Text, nullable=True, comment="Encrypted patient demographics (JSON)")

    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    sessions = relationship("Session", back_populates="patient", cascade="all, delete-orphan")
    records = relationship("MedicalRecord", back_populates="patient", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])

    # Indexes for common queries
    __table_args__ = (
        Index('idx_patient_mrn', 'mrn'),
        Index('idx_patient_name', 'full_name'),
        Index('idx_patient_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<Patient(id={self.id}, mrn={self.mrn}, name={self.full_name})>"


class User(Base):
    """
    User accounts for doctors, nurses, admins, and medical assistants.
    Handles authentication and role-based access control.
    """
    __tablename__ = "users"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Authentication
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)

    # Profile
    full_name = Column(String(200), nullable=True)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.MEDICAL_ASSISTANT)

    # RBAC - Role-Based Access Control
    # Stores additional permissions as JSON array
    permissions = Column(JSON, nullable=True, comment="Additional permissions beyond role")

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    created_patients = relationship("Patient", foreign_keys="Patient.created_by", back_populates="creator")
    sessions_as_doctor = relationship("Session", back_populates="doctor")
    created_records = relationship("MedicalRecord", foreign_keys="MedicalRecord.created_by", back_populates="creator")
    finalized_records = relationship("MedicalRecord", foreign_keys="MedicalRecord.finalized_by", overlaps="finalizer")
    audit_logs = relationship("AuditLog", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class Session(Base):
    """
    Transcription session tracking.
    Represents a single visit/encounter with audio transcription.
    """
    __tablename__ = "sessions"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Foreign keys
    patient_id = Column(String(50), ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)

    # Session metadata
    status = Column(SQLEnum(SessionStatus), nullable=False, default=SessionStatus.ACTIVE, index=True)
    visit_type = Column(String(100), nullable=True, comment="Type of visit (consultation, follow-up, etc.)")

    # Workflow state storage
    workflow_state = Column(JSON, nullable=True, comment="LangGraph workflow state (serialized)")
    checkpoint_id = Column(String(100), nullable=True, comment="LangGraph checkpoint ID")

    # Audio/transcription metadata
    audio_file_path = Column(String(500), nullable=True)
    transcription_file_path = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    patient = relationship("Patient", back_populates="sessions")
    doctor = relationship("User", back_populates="sessions_as_doctor")
    records = relationship("MedicalRecord", back_populates="session", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_session_patient', 'patient_id'),
        Index('idx_session_doctor', 'doctor_id'),
        Index('idx_session_status', 'status'),
        Index('idx_session_started_at', 'started_at'),
    )

    def __repr__(self):
        return f"<Session(id={self.id}, patient_id={self.patient_id}, status={self.status})>"


class MedicalRecord(Base):
    """
    Structured medical records generated from transcriptions.
    Stores the final output of the LangGraph workflow.
    """
    __tablename__ = "medical_records"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Foreign keys
    patient_id = Column(String(50), ForeignKey("patients.id"), nullable=False, index=True)
    session_id = Column(String(50), ForeignKey("sessions.id"), nullable=False, index=True)

    # Structured data from record_schema.py
    # This contains: patient, visit, diagnoses, medications, allergies, problems, labs, procedures, notes
    structured_data = Column(JSON, nullable=False, comment="Complete structured record (StructuredRecord schema)")

    # Clinical suggestions from decision support engine
    clinical_suggestions = Column(JSON, nullable=True, comment="Allergy alerts, drug interactions, etc.")

    # Generated clinical note (SOAP format)
    soap_note = Column(Text, nullable=True, comment="Generated SOAP note")

    # Validation and quality
    validation_report = Column(JSON, nullable=True, comment="Schema validation results")
    conflict_report = Column(JSON, nullable=True, comment="Conflict resolution results")
    confidence_score = Column(Integer, nullable=True, comment="Overall confidence score (0-100)")

    # Document versions
    version = Column(Integer, default=1, nullable=False)
    is_final = Column(Boolean, default=False, nullable=False, comment="Finalized after human review")

    # Metadata
    record_type = Column(String(50), nullable=True, comment="SOAP, Discharge, Consultation, Progress")
    template_used = Column(String(100), nullable=True)

    # Audit
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    finalized_at = Column(DateTime, nullable=True)
    finalized_by = Column(String(50), ForeignKey("users.id"), nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="records")
    session = relationship("Session", back_populates="records")
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_records")
    finalizer = relationship("User", foreign_keys=[finalized_by])

    # Indexes
    __table_args__ = (
        Index('idx_record_patient', 'patient_id'),
        Index('idx_record_session', 'session_id'),
        Index('idx_record_created_at', 'created_at'),
        Index('idx_record_is_final', 'is_final'),
    )

    def __repr__(self):
        return f"<MedicalRecord(id={self.id}, patient_id={self.patient_id}, version={self.version})>"


class AuditLog(Base):
    """
    Audit trail for HIPAA compliance.
    Logs all access to patient data and sensitive operations.
    """
    __tablename__ = "audit_logs"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Who
    user_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)
    user_role = Column(String(50), nullable=True)

    # What
    action = Column(String(100), nullable=False, index=True, comment="read, write, delete, export, etc.")
    resource_type = Column(String(50), nullable=False, comment="patient, record, session, etc.")
    resource_id = Column(String(50), nullable=False, index=True)

    # When
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Where (network)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Additional context
    details = Column(JSON, nullable=True, comment="Additional context about the action")
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")

    # Indexes for audit queries
    __table_args__ = (
        Index('idx_audit_user', 'user_id'),
        Index('idx_audit_resource', 'resource_type', 'resource_id'),
        Index('idx_audit_timestamp', 'timestamp'),
        Index('idx_audit_action', 'action'),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, user_id={self.user_id}, action={self.action}, resource={self.resource_type}:{self.resource_id})>"


class WorkflowCheckpoint(Base):
    """
    LangGraph workflow checkpoints for resumable execution.
    Stores intermediate workflow state for human-in-the-loop review.
    """
    __tablename__ = "workflow_checkpoints"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Foreign key
    session_id = Column(String(50), ForeignKey("sessions.id"), nullable=False, index=True)

    # Checkpoint metadata
    checkpoint_name = Column(String(100), nullable=False, comment="Node name where checkpoint was created")
    thread_id = Column(String(100), nullable=False, index=True)

    # State storage
    state_data = Column(JSON, nullable=False, comment="Complete GraphState snapshot")

    # Status
    is_resumable = Column(Boolean, default=True, nullable=False)
    needs_human_review = Column(Boolean, default=False, nullable=False)
    review_completed = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resumed_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_checkpoint_session', 'session_id'),
        Index('idx_checkpoint_thread', 'thread_id'),
        Index('idx_checkpoint_needs_review', 'needs_human_review'),
    )

    def __repr__(self):
        return f"<WorkflowCheckpoint(id={self.id}, session_id={self.session_id}, checkpoint={self.checkpoint_name})>"


# ─── Document model (OCR pipeline) ─────────────────────────────────────────

class OCRStatus(str, enum.Enum):
    """Document OCR processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """
    Uploaded medical documents tracked through the OCR pipeline.
    Stores file metadata, OCR results, extracted fields, and conflicts.
    """
    __tablename__ = "documents"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Foreign keys
    session_id = Column(String(50), ForeignKey("sessions.id"), nullable=False, index=True)
    patient_id = Column(String(50), ForeignKey("patients.id"), nullable=True, index=True)

    # File metadata
    original_filename = Column(String(500), nullable=False)
    stored_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=True, comment="pdf, image, text")
    file_size = Column(Integer, nullable=True)

    # OCR pipeline results
    ocr_status = Column(SQLEnum(OCRStatus), default=OCRStatus.PENDING, nullable=False, index=True)
    document_type = Column(String(50), nullable=True, comment="lab_report, prescription, discharge_summary, etc.")
    classification_confidence = Column(Float, nullable=True)

    # Extracted content
    extracted_text = Column(Text, nullable=True, comment="Full normalized OCR text")
    structured_fields = Column(JSON, nullable=True, comment="List of ExtractedField dicts")
    confidence_map = Column(JSON, nullable=True, comment="Per-field confidence scores")
    conflicts = Column(JSON, nullable=True, comment="List of ConflictItem dicts")

    # Metrics
    overall_confidence = Column(Float, nullable=True)
    page_count = Column(Integer, nullable=True)
    field_count = Column(Integer, nullable=True)
    conflict_count = Column(Integer, nullable=True)
    processing_errors = Column(JSON, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_document_session', 'session_id'),
        Index('idx_document_patient', 'patient_id'),
        Index('idx_document_status', 'ocr_status'),
        Index('idx_document_type', 'document_type'),
    )

    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.original_filename}, status={self.ocr_status})>"


# ─── Embedding tables (pgvector) ───────────────────────────────────────────

# Embedding dimension — matches BioLord-2023-M / PubMedBERT
EMBEDDING_DIM = 768


class ClinicalEmbedding(Base):
    """
    Vector embeddings for individual clinical facts (allergies, meds, diagnoses, etc.).

    Each row represents one grounded fact extracted from a session,
    stored as a vector(768) alongside the structured JSON for hybrid
    retrieval (semantic search + exact match).

    Lifecycle: created at persist_results, queried at load_patient_context
    and cross-visit contradiction detection.
    """
    __tablename__ = "clinical_embeddings"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    patient_id = Column(String(50), ForeignKey("patients.id"), nullable=False, index=True)
    session_id = Column(String(50), ForeignKey("sessions.id"), nullable=False, index=True)
    record_id = Column(String(50), ForeignKey("medical_records.id"), nullable=True, index=True)

    # Fact metadata
    fact_type = Column(
        String(50), nullable=False, index=True,
        comment="allergy, medication, diagnosis, vital, lab_result, procedure, problem"
    )
    fact_key = Column(
        String(200), nullable=False,
        comment="Canonical key, e.g. 'penicillin' for an allergy"
    )
    fact_data = Column(JSON, nullable=False, comment="Full structured fact (same shape as candidate_facts)")

    # Embedding vector (768-dim, BioLord-2023-M or PubMedBERT)
    embedding = Column(Vector(EMBEDDING_DIM) if Vector else Text, nullable=False, comment="Fact text embedding")

    # Grounding & confidence
    source_span = Column(Text, nullable=True, comment="Original transcript span that produced this fact")
    grounding_score = Column(Float, nullable=True, comment="Cosine sim between source_span and extracted fact")
    confidence = Column(Float, nullable=False, default=0.5, comment="Extraction confidence (0.0–1.0)")
    is_final = Column(Boolean, default=False, nullable=False, comment="True after human review or high-confidence persistence")

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    patient = relationship("Patient", backref="clinical_embeddings")
    session = relationship("Session", backref="clinical_embeddings")

    __table_args__ = (
        Index('idx_ce_patient_type', 'patient_id', 'fact_type'),
        Index('idx_ce_session', 'session_id'),
        Index('idx_ce_is_final', 'is_final'),
    )

    def __repr__(self):
        return f"<ClinicalEmbedding(id={self.id}, patient={self.patient_id}, type={self.fact_type}, key={self.fact_key})>"


class ChunkEmbedding(Base):
    """
    Vector embeddings for transcript/document chunks.

    Stores embeddings generated during segment_and_chunk so that
    retrieve_evidence can use cosine-distance search instead of
    O(n*m) SequenceMatcher.

    Lifecycle: created during ingest/segment, queried at retrieve_evidence
    and grounding verification.
    """
    __tablename__ = "chunk_embeddings"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    session_id = Column(String(50), ForeignKey("sessions.id"), nullable=False, index=True)

    # Chunk metadata
    chunk_id = Column(String(100), nullable=False, index=True, comment="Matches ChunkArtifact.chunk_id")
    source_type = Column(String(20), nullable=False, comment="transcript or document")
    chunk_text = Column(Text, nullable=False, comment="Original chunk text")

    # Embedding vector
    embedding = Column(Vector(EMBEDDING_DIM) if Vector else Text, nullable=False, comment="Chunk text embedding")

    # Timing (if from transcript)
    start_time = Column(Float, nullable=True, comment="Segment start time in seconds")
    end_time = Column(Float, nullable=True, comment="Segment end time in seconds")

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("Session", backref="chunk_embeddings")

    __table_args__ = (
        Index('idx_chk_session', 'session_id'),
        Index('idx_chk_chunk_id', 'chunk_id'),
    )

    def __repr__(self):
        return f"<ChunkEmbedding(id={self.id}, session={self.session_id}, chunk={self.chunk_id})>"
