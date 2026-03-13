"""
Pytest configuration and shared fixtures.
"""

import pytest
from datetime import datetime
from typing import Dict, List, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from faker import Faker

from app.database.base import Base
from app.database.models import Patient, MedicalRecord, User
from app.agents.state import GraphState, TranscriptSegment, ChunkArtifact, CandidateFact


# Initialize Faker for generating test data
fake = Faker()


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def test_engine():
    """Create a test database engine (in-memory SQLite)."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Create a new database session for a test, using a transaction that gets
    rolled back after the test so that each test starts with a clean slate."""
    connection = test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_patient(db_session: Session) -> Patient:
    """Create a sample patient in the database."""
    patient = Patient(
        id="PAT001",
        mrn="MRN123456",
        full_name="John Doe",
        dob=datetime(1980, 5, 15),
        sex="M"
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


@pytest.fixture
def sample_user(db_session: Session) -> User:
    """Create a sample user in the database."""
    user = User(
        id="USER001",
        username="dr.smith",
        email="dr.smith@hospital.com",
        hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYzS.sC",
        role="doctor",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_medical_record(db_session: Session, sample_patient: Patient, sample_user: User) -> MedicalRecord:
    """Create a sample medical record in the database."""
    record = MedicalRecord(
        id="REC001",
        patient_id=sample_patient.id,
        session_id="SESS001",
        structured_data={
            "medications": [
                {"name": "Aspirin", "dose": "81mg", "route": "PO", "frequency": "daily"}
            ],
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
            ],
            "diagnoses": [
                {"code": "I10", "description": "Essential hypertension", "status": "active"}
            ]
        },
        clinical_suggestions={},
        created_by=sample_user.id
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


# ============================================================================
# LangGraph State Fixtures
# ============================================================================

@pytest.fixture
def sample_transcript_segment() -> TranscriptSegment:
    """Create a sample transcript segment."""
    return {
        "start": 0.0,
        "end": 5.0,
        "speaker": "Doctor",
        "raw_text": "Patient presents with chest pain and shortness of breath.",
        "cleaned_text": None,
        "uncertainties": [],
        "confidence": "high"
    }


@pytest.fixture
def sample_transcript_segments() -> List[TranscriptSegment]:
    """Create multiple sample transcript segments."""
    return [
        {
            "start": 0.0,
            "end": 3.0,
            "speaker": "Doctor",
            "raw_text": "Um, so how are you feeling today?",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "high"
        },
        {
            "start": 3.0,
            "end": 6.0,
            "speaker": "Patient",
            "raw_text": "Well, you know, I've been having this pain in my chest.",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "medium"
        },
        {
            "start": 6.0,
            "end": 9.0,
            "speaker": "Doctor",
            "raw_text": "I see. Can you describe the pain?",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "high"
        },
        {
            "start": 9.0,
            "end": 12.0,
            "speaker": "Patient",
            "raw_text": "It's like, um, a pressure. You know what I mean?",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "medium"
        }
    ]


@pytest.fixture
def sample_chunk_artifact() -> ChunkArtifact:
    """Create a sample chunk artifact."""
    return {
        "chunk_id": "chunk_001",
        "text": "Patient presents with chest pain described as pressure-like sensation. Duration approximately 2 hours.",
        "speaker": "Doctor",
        "start_time": 0.0,
        "end_time": 10.0,
        "metadata": {
            "source": "conversation_log",
            "turn_index": 0
        }
    }


@pytest.fixture
def sample_chunks() -> List[ChunkArtifact]:
    """Create multiple sample chunks."""
    return [
        {
            "chunk_id": "chunk_001",
            "text": "Patient presents with chest pain described as pressure-like sensation.",
            "speaker": "Doctor",
            "start_time": 0.0,
            "end_time": 5.0,
            "metadata": {"source": "conversation_log", "turn_index": 0}
        },
        {
            "chunk_id": "chunk_002",
            "text": "Pain duration approximately 2 hours. No radiation to arm or jaw.",
            "speaker": "Doctor",
            "start_time": 5.0,
            "end_time": 10.0,
            "metadata": {"source": "conversation_log", "turn_index": 0}
        },
        {
            "chunk_id": "chunk_003",
            "text": "Patient denies shortness of breath. Blood pressure 140/90.",
            "speaker": "Doctor",
            "start_time": 10.0,
            "end_time": 15.0,
            "metadata": {"source": "conversation_log", "turn_index": 1}
        }
    ]


@pytest.fixture
def sample_candidate_fact() -> CandidateFact:
    """Create a sample candidate fact."""
    return {
        "fact_id": "fact_001",
        "category": "chief_complaint",
        "field": "description",
        "value": "Chest pain",
        "confidence": 0.9,
        "source_node": "extract_candidates"
    }


@pytest.fixture
def sample_candidate_facts() -> List[CandidateFact]:
    """Create multiple sample candidate facts."""
    return [
        {
            "fact_id": "fact_001",
            "type": "diagnosis",
            "value": {"description": "Chest pain"},
            "provenance": {"evidence": [{"source": "transcript", "snippet": "patient complains of chest pain", "strength": 0.9}]},
            "confidence": 0.9,
        },
        {
            "fact_id": "fact_002",
            "type": "vital",
            "value": {"type": "BP", "value": "140/90 mmHg"},
            "provenance": {"evidence": [{"source": "transcript", "snippet": "blood pressure 140 over 90", "strength": 0.85}]},
            "confidence": 0.85,
        },
        {
            "fact_id": "fact_003",
            "type": "medication",
            "value": {"name": "Aspirin", "dose": "81mg", "frequency": "daily"},
            "provenance": {"evidence": [{"source": "transcript", "snippet": "taking aspirin 81mg daily", "strength": 0.95}]},
            "confidence": 0.95,
        },
    ]


@pytest.fixture
def minimal_graph_state() -> GraphState:
    """Create a minimal graph state for testing."""
    return {
        "session_id": "test_session_001",
        "patient_id": "PAT001",
        "doctor_id": "DOC001",
        "conversation_log": [],
        "new_segments": [],
        "session_summary": None,
        "patient_record_fields": None,
        "message": None,
        "flags": {},
        "inputs": {},
        "documents": [],
        "chunks": [],
        "candidate_facts": [],
        "evidence_map": {},
        "structured_record": {},
        "validation_report": None,
        "conflict_report": None,
        "clinical_note": None,
        "controls": {
            "attempts": {},
            "budget": {},
            "trace_log": []
        }
    }


@pytest.fixture
def complete_graph_state(
    sample_transcript_segments,
    sample_chunks,
    sample_candidate_facts
) -> GraphState:
    """Create a complete graph state with all fields populated."""
    return {
        "session_id": "test_session_001",
        "patient_id": "PAT001",
        "doctor_id": "DOC001",
        "conversation_log": [
            {
                "turn_index": 0,
                "speaker": "Doctor",
                "text": "How are you feeling today?",
                "timestamp": 0.0
            }
        ],
        "new_segments": sample_transcript_segments,
        "session_summary": "Patient presenting with chest pain.",
        "patient_record_fields": None,
        "message": None,
        "flags": {},
        "inputs": {},
        "documents": [],
        "chunks": sample_chunks,
        "candidate_facts": sample_candidate_facts,
        "evidence_map": {},
        "structured_record": {
            "chief_complaint": {"description": "Chest pain"},
            "vital_signs": {"blood_pressure": "140/90 mmHg"}
        },
        "validation_report": None,
        "conflict_report": None,
        "clinical_note": None,
        "controls": {
            "attempts": {},
            "budget": {},
            "trace_log": []
        }
    }


# ============================================================================
# Validation Report Fixtures
# ============================================================================

@pytest.fixture
def validation_report_with_errors():
    """Create a validation report with schema errors."""
    return {
        "schema_errors": [
            {"field": "medications[0].dose", "error": "Invalid format"},
            {"field": "vital_signs.temperature", "error": "Missing required field"}
        ],
        "missing_fields": ["allergies", "past_medical_history"],
        "confidence": 0.65,
        "needs_review": True
    }


@pytest.fixture
def validation_report_clean():
    """Create a clean validation report with no errors."""
    return {
        "schema_errors": [],
        "missing_fields": [],
        "confidence": 0.92,
        "needs_review": False
    }


@pytest.fixture
def conflict_report_with_conflicts():
    """Create a conflict report with unresolved conflicts."""
    return {
        "conflicts": [
            "Blood pressure: 120/80 vs 140/90",
            "Medication dose: 81mg vs 100mg"
        ],
        "unresolved": True
    }


@pytest.fixture
def conflict_report_clean():
    """Create a conflict report with no conflicts."""
    return {
        "conflicts": [],
        "unresolved": False
    }
