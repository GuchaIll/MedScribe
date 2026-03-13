
from typing import List, Optional, TypedDict, Dict, Any, Literal



class TranscriptSegment(TypedDict):
    start: float
    end: float
    speaker: Optional[str]
    raw_text: str
    cleaned_text: Optional[str]
    uncertainties: List[str]
    confidence: Optional[str]


class ConversationTurn(TypedDict):
    timestamp: float
    segments: List[TranscriptSegment]


class DocumentArtifact(TypedDict):
    document_id: str
    source_type: Literal["pdf", "image", "text", "unknown"]
    extracted_text: str
    tables: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ChunkArtifact(TypedDict):
    chunk_id: str
    source: Literal["transcript", "document"]
    source_id: str
    text: str
    start: Optional[float]
    end: Optional[float]
    metadata: Dict[str, Any]


class CandidateFact(TypedDict):
    fact_id: str
    type: str
    value: Any
    provenance: Dict[str, Any]
    confidence: Optional[float]


class EvidenceItem(TypedDict):
    source_id: str
    source_type: Literal["transcript", "document"]
    snippet: str
    confidence: Optional[float]
    metadata: Dict[str, Any]


class ValidationReport(TypedDict):
    schema_errors: List[str]
    missing_fields: List[str]
    conflicts: List[str]
    needs_review: bool
    confidence: Optional[float]
    details: Dict[str, Any]


class ConflictReport(TypedDict):
    unresolved: bool
    conflicts: List[str]
    resolutions: List[str]
    evidence: Dict[str, Any]


class Controls(TypedDict):
    attempts: Dict[str, int]
    budget: Dict[str, Any]
    trace_log: List[Dict[str, Any]]


class GraphState(TypedDict):
    session_id: str
    patient_id: str
    doctor_id: str

    conversation_log: List[ConversationTurn]
    new_segments: List[TranscriptSegment]

    session_summary: Optional[Dict[str, Any]]
    patient_record_fields: Optional[Dict[str, Any]]

    message: Optional[str]
    flags: Dict[str, bool]

    # Artifact-driven pipeline additions
    inputs: Dict[str, Any]
    documents: List[DocumentArtifact]
    chunks: List[ChunkArtifact]
    candidate_facts: List[CandidateFact]
    evidence_map: Dict[str, List[EvidenceItem]]
    structured_record: Dict[str, Any]
    validation_report: Optional[ValidationReport]
    conflict_report: Optional[ConflictReport]
    clinical_note: Optional[str]
    clinical_suggestions: Optional[Dict[str, Any]]  # Clinical decision support suggestions
    is_new_patient: bool  # Skip DB lookups for brand-new patients
    controls: Controls


