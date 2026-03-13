"""
Pydantic request/response schemas for the API.

Shared between routes so there's a single source of truth
for request validation and OpenAPI documentation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Session ─────────────────────────────────────────────────────────────────

class SessionStartResponse(BaseModel):
    session_id: str
    message: str


class SessionEndResponse(BaseModel):
    message: str


class TranscribeRequest(BaseModel):
    text: Optional[str] = None
    speaker: Optional[str] = "Unknown"


class TranscribeResponse(BaseModel):
    session_id: str
    speaker: str
    transcription: str
    source: str
    agent_message: Optional[str] = None


# ── Transcription pipeline ──────────────────────────────────────────────────

class TranscriptSegmentSchema(BaseModel):
    start: float
    end: float
    speaker: Optional[str] = None
    raw_text: str
    confidence: Optional[str] = None


class RunPipelineRequest(BaseModel):
    session_id: str
    patient_id: str
    doctor_id: str
    segments: List[TranscriptSegmentSchema]
    is_new_patient: bool = Field(
        default=False,
        description="Skip DB lookups for demographics/prior records when True (new patient)."
    )


class RunPipelineResponse(BaseModel):
    session_id: str
    clinical_note: Optional[str] = None
    structured_record: Optional[Dict[str, Any]] = None
    clinical_suggestions: Optional[Dict[str, Any]] = None
    validation_report: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# ── Records ─────────────────────────────────────────────────────────────────

class GenerateRecordRequest(BaseModel):
    record: Dict[str, Any] = Field(
        ..., description="Structured medical record dict"
    )
    template: str = Field(default="soap")
    clinical_suggestions: Optional[Dict[str, Any]] = None
    format: str = Field(default="html")


class TemplateInfo(BaseModel):
    name: str
    description: str
    formats: List[str]


# ── Clinical ────────────────────────────────────────────────────────────────

class ClinicalSuggestionsRequest(BaseModel):
    current_record: Dict[str, Any]
    patient_history: Optional[Dict[str, Any]] = None
    use_external_database: bool = False


class AllergyCheckRequest(BaseModel):
    medications: List[Dict[str, Any]]
    allergies: List[Dict[str, Any]]


class InteractionCheckRequest(BaseModel):
    medications: List[Dict[str, Any]]


# ── OCR / Document Processing ───────────────────────────────────────────────

class DocumentProcessingResponse(BaseModel):
    """Response from the OCR document processing pipeline."""
    document_id: str
    original_filename: str = ""
    document_type: str = "unknown"
    classification_confidence: float = 0.0
    fields_extracted: int = 0
    conflicts_detected: int = 0
    overall_confidence: float = 0.0
    full_text: Optional[str] = None
    extracted_fields: Optional[List[Dict[str, Any]]] = None
    conflicts: Optional[List[Dict[str, Any]]] = None
    processing_errors: List[str] = Field(default_factory=list)


class ModificationQueueItemSchema(BaseModel):
    """A single item in the modification review queue."""
    item_id: str
    session_id: str = ""
    field_name: str = ""
    extracted_value: str = ""
    corrected_value: Optional[str] = None
    source_document: str = ""
    confidence: float = 0.0
    conflict_reason: str = ""
    severity: str = "medium"
    status: str = "pending"  # pending | accepted | rejected | modified


class QueueUpdateRequest(BaseModel):
    """Request to update a queue item."""
    status: str = Field(..., description="New status: accepted, rejected, or modified")
    corrected_value: Optional[str] = None


# ── Record Commit & Versioning ──────────────────────────────────────────────

class RecordCommitRequest(BaseModel):
    """Commit a physician-reviewed record as final."""
    session_id: str
    record_id: str
    corrections: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional field corrections applied during review",
    )
    template: str = Field(default="soap")
    finalized_by: str = Field(..., description="Doctor/user ID who approved the record")


class RecordCommitResponse(BaseModel):
    record_id: str
    version: int
    is_final: bool
    message: str


class RecordVersionSchema(BaseModel):
    """Summary of a single record version."""
    record_id: str
    version: int
    is_final: bool
    confidence_score: Optional[int] = None
    record_type: Optional[str] = None
    created_by: str
    created_at: str
    finalized_at: Optional[str] = None
    finalized_by: Optional[str] = None


class RegenerateRecordRequest(BaseModel):
    """Regenerate a record incorporating physician feedback."""
    record: Dict[str, Any] = Field(
        ..., description="Current structured medical record dict"
    )
    template: str = Field(default="soap")
    clinical_suggestions: Optional[Dict[str, Any]] = None
    feedback: str = Field(
        ..., description="Physician feedback/corrections to incorporate"
    )
    format: str = Field(default="html")
    iteration: int = Field(default=1, description="Regeneration attempt number")


# ── Clinical Override ───────────────────────────────────────────────────────

class ClinicalOverrideRequest(BaseModel):
    """Physician override of a clinical alert."""
    session_id: str
    alert_type: str = Field(
        ..., description="allergy_conflict | drug_interaction | contraindication | dosage_issue"
    )
    alert_summary: str = Field(..., description="Brief description of the alert being overridden")
    justification: str = Field(..., description="Clinical justification for the override")
    overridden_by: str = Field(..., description="Doctor/user ID")


class ClinicalOverrideResponse(BaseModel):
    override_id: int
    message: str
    logged: bool


# ── Lab Interpretation ──────────────────────────────────────────────────────

class LabInterpretationRequest(BaseModel):
    """Request lab result interpretation."""
    labs: List[Dict[str, Any]] = Field(
        ..., description="Lab results with test_name, value, unit"
    )
    patient_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Patient age, sex, conditions for contextual interpretation",
    )


class LabInterpretationResponse(BaseModel):
    interpretations: List[Dict[str, Any]]
    risk_flags: List[str] = Field(default_factory=list)
    summary: str = ""


# ── Patient Model / Trends ──────────────────────────────────────────────────

class LabTrendSchema(BaseModel):
    """Time-series lab trend for a single test."""
    test_name: str
    data_points: List[Dict[str, Any]]
    trend_direction: str = "stable"  # improving | worsening | stable | fluctuating
    latest_value: Optional[str] = None
    latest_status: str = "normal"  # normal | borderline | abnormal | critical


class PatientProfileResponse(BaseModel):
    """Unified longitudinal patient profile."""
    patient_id: str
    patient_info: Dict[str, Any]
    lab_trends: List[LabTrendSchema] = Field(default_factory=list)
    medication_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    risk_score: Optional[Dict[str, Any]] = None
    visit_count: int = 0
