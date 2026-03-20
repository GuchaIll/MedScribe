"""
Unit tests for long-term database persistence.

Validates:
  - SessionService._persist_record_to_db() creates MedicalRecord correctly
  - end_session() flushes to DB and removes from _store
  - persist_results_node creates versioned records with correct is_final logic
  - Clinical embeddings stored with grounding scores and confidence gating
  - RecordRepository queries (get_for_patient, get_for_session, create)
  - Version incrementing for multiple records in the same session
  - Confidence score computation heuristic
"""

import uuid
import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as DBSession

from app.database.base import Base
from app.database.models import (
    Patient, User, Session as DBSessionModel, MedicalRecord,
    ClinicalEmbedding, ChunkEmbedding, AuditLog,
    UserRole, SessionStatus, EMBEDDING_DIM,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db_engine():
    """In-memory SQLite engine for fast tests (no pgvector)."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Replace Vector columns with Text for SQLite compatibility
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Scoped DB session that rolls back after each test."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def seeded_db(db_session):
    """DB with a test patient, user, and session pre-created."""
    user = User(
        id="D001",
        username="dr_smith",
        email="smith@hospital.org",
        hashed_password="fakehash",
        full_name="Dr. Smith",
        role=UserRole.DOCTOR,
    )
    patient = Patient(
        id="P001",
        mrn="MRN-TEST-001",
        full_name="Test Patient",
        dob=datetime(1990, 1, 15),
        age=35,
        sex="Male",
    )
    db_session_model = DBSessionModel(
        id="S001",
        patient_id="P001",
        doctor_id="D001",
        status=SessionStatus.ACTIVE,
    )
    db_session.add_all([user, patient, db_session_model])
    db_session.commit()
    return {
        "user": user,
        "patient": patient,
        "session": db_session_model,
        "db": db_session,
    }


# ── RecordRepository Tests ─────────────────────────────────────────────────

class TestRecordRepository:
    """Tests for RecordRepository CRUD operations."""

    def test_create_record(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        record = MedicalRecord(
            id="R001",
            patient_id="P001",
            session_id="S001",
            structured_data={"demographics": {"full_name": "Test Patient"}},
            confidence_score=85,
            version=1,
            is_final=True,
            record_type="SOAP",
            created_by="D001",
        )
        created = repo.create(record)
        assert created.id == "R001"
        assert created.patient_id == "P001"

    def test_get_by_id(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        record = MedicalRecord(
            id="R002",
            patient_id="P001",
            session_id="S001",
            structured_data={"vitals": {"heart_rate": 72}},
            version=1,
            is_final=False,
            created_by="D001",
        )
        repo.create(record)
        seeded_db["db"].commit()

        fetched = repo.get_by_id("R002")
        assert fetched is not None
        assert fetched.structured_data["vitals"]["heart_rate"] == 72

    def test_get_by_id_nonexistent(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])
        assert repo.get_by_id("nonexistent") is None

    def test_get_for_patient(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        for i in range(3):
            repo.create(MedicalRecord(
                id=f"R{i:03d}",
                patient_id="P001",
                session_id="S001",
                structured_data={"version": i},
                version=i + 1,
                is_final=i == 2,
                created_by="D001",
            ))
        seeded_db["db"].commit()

        records = repo.get_for_patient("P001")
        assert len(records) == 3

    def test_get_for_patient_with_limit(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        for i in range(5):
            repo.create(MedicalRecord(
                id=f"RL{i:03d}",
                patient_id="P001",
                session_id="S001",
                structured_data={"version": i},
                version=i + 1,
                is_final=False,
                created_by="D001",
            ))
        seeded_db["db"].commit()

        records = repo.get_for_patient("P001", limit=3)
        assert len(records) == 3

    def test_get_for_session(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        repo.create(MedicalRecord(
            id="RS001",
            patient_id="P001",
            session_id="S001",
            structured_data={"note": "session record"},
            version=1,
            is_final=False,
            created_by="D001",
        ))
        seeded_db["db"].commit()

        records = repo.get_for_session("S001")
        assert len(records) == 1
        assert records[0].id == "RS001"

    def test_count_for_patient(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        for i in range(4):
            repo.create(MedicalRecord(
                id=f"RC{i:03d}",
                patient_id="P001",
                session_id="S001",
                structured_data={},
                version=i + 1,
                is_final=False,
                created_by="D001",
            ))
        seeded_db["db"].commit()

        count = repo.count_for_patient("P001")
        assert count == 4

    def test_update_structured_data(self, seeded_db):
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])

        repo.create(MedicalRecord(
            id="RU001",
            patient_id="P001",
            session_id="S001",
            structured_data={"old": "data"},
            version=1,
            is_final=False,
            created_by="D001",
        ))
        seeded_db["db"].commit()

        updated = repo.update_structured_data("RU001", {"new": "data"})
        assert updated is not None
        assert updated.structured_data == {"new": "data"}


# ── SessionService._persist_record_to_db Tests ─────────────────────────────

class TestSessionServiceDBPersistence:
    """Tests for SessionService integration with DB."""

    def test_persist_record_to_db_creates_record(self, seeded_db):
        """_persist_record_to_db should create a MedicalRecord row."""
        from app.services.session_service import SessionService

        svc = SessionService(db_session=seeded_db["db"])
        sid = svc.start_session(patient_id="P001", doctor_id="D001")["session_id"]

        # Merge some data
        svc.merge_structured_record(sid, {
            "medications": [{"name": "Lisinopril", "dose": "10mg"}],
        }, source="test")

        session = svc._store[sid]
        record = session["structured_record"]

        svc._persist_record_to_db(sid, session, record)

        # Verify record was created
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])
        records = repo.get_for_patient("P001")
        assert len(records) >= 1

        latest = records[0]
        assert latest.patient_id == "P001"
        assert latest.is_final is False
        assert latest.record_type == "session_consolidated"
        assert "medications" in latest.structured_data

    def test_persist_strips_metadata_keys(self, seeded_db):
        """Metadata keys (_conflicts, _low_confidence, _db_seeded_fields) should be stripped."""
        from app.services.session_service import SessionService

        svc = SessionService(db_session=seeded_db["db"])
        sid = svc.start_session(patient_id="P001", doctor_id="D001")["session_id"]

        svc.merge_structured_record(sid, {
            "medications": [{"name": "Aspirin"}],
            "_low_confidence": [{"field": "medications.0.dose"}],
        }, source="test")

        session = svc._store[sid]
        record = session["structured_record"]

        svc._persist_record_to_db(sid, session, record)

        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])
        records = repo.get_for_patient("P001")
        latest = records[0]

        # Internal metadata keys should not be in persisted structured_data
        assert "_conflicts" not in latest.structured_data
        assert "_low_confidence" not in latest.structured_data
        assert "_db_seeded_fields" not in latest.structured_data

    def test_persist_preserves_conflict_report(self, seeded_db):
        """Conflict report should be stored in the separate conflict_report column."""
        from app.services.session_service import SessionService

        svc = SessionService(db_session=seeded_db["db"])
        sid = svc.start_session(patient_id="P001", doctor_id="D001")["session_id"]

        svc.merge_structured_record(sid, {
            "demographics": {
                "full_name": "John Doe",
                "date_of_birth": None, "age": None, "sex": None,
                "gender": None, "mrn": None,
                "contact_info": {"phone": None, "email": None, "address": None,
                                 "city": None, "state": None, "zip": None},
                "insurance": {"provider": None, "policy_number": None,
                             "group_number": None, "subscriber_name": None},
                "emergency_contact": {"name": None, "relationship": None, "phone": None},
            }
        }, source="ocr")
        # Create a conflict
        svc.merge_structured_record(sid, {
            "demographics": {
                "full_name": "Jane Smith",
                "date_of_birth": None, "age": None, "sex": None,
                "gender": None, "mrn": None,
                "contact_info": {"phone": None, "email": None, "address": None,
                                 "city": None, "state": None, "zip": None},
                "insurance": {"provider": None, "policy_number": None,
                             "group_number": None, "subscriber_name": None},
                "emergency_contact": {"name": None, "relationship": None, "phone": None},
            }
        }, source="transcript")

        session = svc._store[sid]
        record = session["structured_record"]
        svc._persist_record_to_db(sid, session, record)

        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])
        latest = repo.get_for_patient("P001")[0]

        assert latest.conflict_report is not None
        assert len(latest.conflict_report) >= 1

    def test_end_session_flushes_to_db(self, seeded_db):
        """end_session should persist the record to DB and remove from _store."""
        from app.services.session_service import SessionService

        svc = SessionService(db_session=seeded_db["db"])
        sid = svc.start_session(patient_id="P001", doctor_id="D001")["session_id"]

        svc.merge_structured_record(sid, {
            "vitals": {"blood_pressure": "120/80", "heart_rate": 72},
        }, source="monitor")

        svc.end_session(sid)

        # Session should be removed from in-memory store
        assert sid not in svc._store

        # Record should exist in DB
        from app.database.repositories.record_repo import RecordRepository
        repo = RecordRepository(seeded_db["db"])
        records = repo.get_for_patient("P001")
        assert len(records) >= 1


# ── persist_results_node Tests ──────────────────────────────────────────────

class TestPersistResultsNode:
    """Tests for the pipeline persist_results_node."""

    def _make_ctx(self, record_repo=None, embedding_service=None,
                  session_repo=None, db_session_factory=None):
        """Create a mock AgentContext."""
        ctx = MagicMock()
        ctx.record_repo = record_repo
        ctx.embedding_service = embedding_service
        ctx.session_repo = session_repo
        ctx.db_session_factory = db_session_factory
        ctx.grounding_threshold = 0.65
        ctx.persistence_floor = 0.60
        return ctx

    def _make_state(self, **overrides):
        """Create a minimal valid GraphState."""
        state = {
            "session_id": "S001",
            "patient_id": "P001",
            "doctor_id": "D001",
            "structured_record": {
                "demographics": {"full_name": "Test Patient"},
                "medications": [{"name": "Aspirin", "dose": "81mg"}],
            },
            "candidate_facts": [],
            "evidence_map": {},
            "clinical_note": "SOAP note text",
            "clinical_suggestions": None,
            "validation_report": None,
            "conflict_report": None,
            "controls": {"attempts": {}, "budget": {}, "trace_log": []},
            "message": "",
        }
        state.update(overrides)
        return state

    def test_no_db_is_noop(self):
        """Without DB services, persist_results should be a no-op."""
        from app.agents.nodes.persist_results import persist_results_node

        ctx = self._make_ctx()
        state = self._make_state()

        result = persist_results_node(state, ctx)
        assert "persist_results" in str(result.get("controls", {}).get("trace_log", []))

    def test_creates_medical_record_via_repo(self, seeded_db):
        """Record repo should receive a MedicalRecord with correct fields."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        state = self._make_state()
        result = persist_results_node(state, ctx)

        records = repo.get_for_patient("P001")
        assert len(records) >= 1
        latest = records[0]
        assert latest.patient_id == "P001"
        assert latest.session_id == "S001"
        assert latest.created_by == "D001"
        assert latest.structured_data is not None

    def test_confidence_score_computed(self, seeded_db):
        """Confidence should be computed from validation_report."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        state = self._make_state(
            validation_report={
                "schema_errors": [],
                "missing_fields": ["dob"],
                "conflicts": [],
                "needs_review": False,
            }
        )
        persist_results_node(state, ctx)

        records = repo.get_for_patient("P001")
        latest = records[0]
        # confidence = 100 - 10*0 - 5*1 - 15*0 = 95
        assert latest.confidence_score == 95

    def test_is_final_true_when_high_confidence(self, seeded_db):
        """is_final should be True when confidence >= 80 and not needs_review."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        state = self._make_state(
            validation_report={
                "schema_errors": [],
                "missing_fields": [],
                "conflicts": [],
                "needs_review": False,
            }
        )
        persist_results_node(state, ctx)

        latest = repo.get_for_patient("P001")[0]
        assert latest.is_final is True
        assert latest.confidence_score == 100

    def test_is_final_false_when_needs_review(self, seeded_db):
        """is_final should be False even if confidence is high but needs_review."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        state = self._make_state(
            validation_report={
                "schema_errors": [],
                "missing_fields": [],
                "conflicts": [],
                "needs_review": True,
            }
        )
        persist_results_node(state, ctx)

        latest = repo.get_for_patient("P001")[0]
        assert latest.is_final is False

    def test_is_final_false_when_low_confidence(self, seeded_db):
        """is_final should be False when confidence < 80."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        state = self._make_state(
            validation_report={
                "schema_errors": ["error1", "error2", "error3"],
                "missing_fields": ["a", "b", "c", "d"],
                "conflicts": [],
                "needs_review": False,
            }
        )
        persist_results_node(state, ctx)

        latest = repo.get_for_patient("P001")[0]
        # 100 - 30 - 20 = 50
        assert latest.confidence_score == 50
        assert latest.is_final is False

    def test_version_increments(self, seeded_db):
        """Multiple persist calls for the same session should increment version."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.database.repositories.record_repo import RecordRepository

        repo = RecordRepository(seeded_db["db"])
        ctx = self._make_ctx(
            record_repo=repo,
            db_session_factory=lambda: seeded_db["db"],
        )

        # First persist
        state1 = self._make_state()
        persist_results_node(state1, ctx)

        # Second persist
        state2 = self._make_state(
            structured_record={"demographics": {"full_name": "Updated Patient"}}
        )
        persist_results_node(state2, ctx)

        records = repo.get_for_session("S001")
        versions = sorted([r.version for r in records])
        assert versions == [1, 2]


# ── Clinical Embedding Persistence Tests ────────────────────────────────────

class TestClinicalEmbeddingPersistence:
    """Tests for clinical embedding storage with grounding and confidence gating."""

    def test_store_clinical_embedding_mock(self):
        """Test embedding service stores facts with correct metadata."""
        from app.services.embedding_service import EmbeddingService
        import numpy as np

        # Use a mock DB session
        mock_db = MagicMock()
        svc = EmbeddingService(db=mock_db)

        # Mock the model to avoid loading BioLord
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(768).astype(np.float32)
        svc._model = mock_model

        fact = {
            "type": "medication",
            "value": {"name": "Lisinopril", "dose": "10mg"},
            "confidence": 0.85,
        }

        svc.store_clinical_embedding(
            patient_id="P001",
            session_id="S001",
            fact=fact,
            is_final=True,
            grounding_score=0.78,
            source_span="Patient takes Lisinopril 10mg daily",
        )

        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

        # Verify the ClinicalEmbedding model was created with correct fields
        added_record = mock_db.add.call_args[0][0]
        assert added_record.patient_id == "P001"
        assert added_record.fact_type == "medication"
        assert added_record.confidence == 0.85
        assert added_record.is_final is True
        assert added_record.grounding_score == 0.78

    def test_confidence_gating_below_floor(self):
        """Facts below persistence_floor should be stored with is_final=False."""
        from app.services.embedding_service import EmbeddingService
        import numpy as np

        mock_db = MagicMock()
        svc = EmbeddingService(db=mock_db, persistence_floor=0.60)

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(768).astype(np.float32)
        svc._model = mock_model

        fact = {
            "type": "medication",
            "value": {"name": "Unknown Drug"},
            "confidence": 0.40,  # Below floor
        }

        svc.store_clinical_embedding(
            patient_id="P001",
            session_id="S001",
            fact=fact,
            is_final=True,  # Caller says final, but gating should override
        )

        added_record = mock_db.add.call_args[0][0]
        assert added_record.is_final is False, "Confidence gating should override is_final"

    def test_fact_to_text_conversion(self):
        """_fact_to_text should produce a searchable string."""
        from app.services.embedding_service import EmbeddingService

        svc = EmbeddingService()

        # Dict value
        fact = {"type": "medication", "value": {"name": "Aspirin", "dose": "81mg"}}
        text = svc._fact_to_text(fact)
        assert "medication" in text
        assert "Aspirin" in text

        # String value
        fact2 = {"type": "allergy", "value": "Penicillin"}
        text2 = svc._fact_to_text(fact2)
        assert "allergy" in text2
        assert "Penicillin" in text2

        # List value
        fact3 = {"type": "diagnoses", "value": ["HTN", "DM2"]}
        text3 = svc._fact_to_text(fact3)
        assert "HTN" in text3

    def test_fact_to_key_extraction(self):
        """_fact_to_key should extract canonical dedup key."""
        from app.services.embedding_service import EmbeddingService

        svc = EmbeddingService()

        fact = {"type": "medication", "value": {"name": "Aspirin", "dose": "81mg"}}
        key = svc._fact_to_key(fact)
        assert key == "aspirin"

        fact2 = {"type": "allergy", "value": {"substance": "Penicillin"}}
        key2 = svc._fact_to_key(fact2)
        assert key2 == "penicillin"

    def test_verify_grounding_mock(self):
        """verify_grounding should return (score, is_grounded) tuple."""
        from app.services.embedding_service import EmbeddingService
        import numpy as np

        svc = EmbeddingService(grounding_threshold=0.65)

        # Mock model with controlled embeddings
        mock_model = MagicMock()
        # Two identical normalized vectors -> cosine sim = 1.0
        v = np.array([1.0] + [0.0] * 767, dtype=np.float32)
        v = v / np.linalg.norm(v)
        mock_model.encode.return_value = np.stack([v, v])
        svc._model = mock_model

        score, is_grounded = svc.verify_grounding(
            source_span="patient on aspirin 81mg",
            extracted_text="aspirin 81mg",
        )
        assert is_grounded is True
        assert score >= 0.99

    def test_no_db_skips_storage(self):
        """Without DB session, store methods should log warning but not crash."""
        from app.services.embedding_service import EmbeddingService
        import numpy as np

        svc = EmbeddingService(db=None)

        # Should not raise
        svc.store_clinical_embedding(
            patient_id="P001",
            session_id="S001",
            fact={"type": "medication", "value": "test"},
        )
        svc.store_chunk_embedding(
            session_id="S001",
            chunk_id="C001",
            source_type="transcript",
            chunk_text="test text",
        )

    def test_search_without_db_returns_empty(self):
        """Search methods should return empty list without DB."""
        from app.services.embedding_service import EmbeddingService
        import numpy as np

        svc = EmbeddingService(db=None)
        vec = np.zeros(768, dtype=np.float32)

        assert svc.search_similar_chunks("S001", vec) == []
        assert svc.search_patient_facts("P001", vec) == []
        assert svc.get_patient_facts_by_type("P001", "medication") == []
        assert svc.get_all_patient_facts("P001") == {}


# ── MedicalRecord Model Tests ──────────────────────────────────────────────

class TestMedicalRecordModel:
    """Tests for MedicalRecord model attributes and constraints."""

    def test_record_defaults(self, seeded_db):
        record = MedicalRecord(
            id="RD001",
            patient_id="P001",
            session_id="S001",
            structured_data={"test": True},
            created_by="D001",
        )
        seeded_db["db"].add(record)
        seeded_db["db"].commit()

        fetched = seeded_db["db"].query(MedicalRecord).filter_by(id="RD001").first()
        assert fetched.version == 1
        assert fetched.is_final is False
        assert fetched.created_at is not None

    def test_record_json_data_roundtrip(self, seeded_db):
        """Structured data should survive JSON serialization roundtrip."""
        complex_data = {
            "demographics": {
                "full_name": "John Doe",
                "contact_info": {"phone": "555-0100", "email": "john@test.com"},
            },
            "medications": [
                {"name": "Lisinopril", "dose": "10mg", "frequency": "daily"},
                {"name": "Aspirin", "dose": "81mg", "frequency": "daily"},
            ],
            "vitals": {"blood_pressure": "120/80", "heart_rate": 72},
        }

        record = MedicalRecord(
            id="RJ001",
            patient_id="P001",
            session_id="S001",
            structured_data=complex_data,
            created_by="D001",
        )
        seeded_db["db"].add(record)
        seeded_db["db"].commit()

        fetched = seeded_db["db"].query(MedicalRecord).filter_by(id="RJ001").first()
        assert fetched.structured_data["demographics"]["full_name"] == "John Doe"
        assert len(fetched.structured_data["medications"]) == 2
        assert fetched.structured_data["vitals"]["heart_rate"] == 72

    def test_multiple_records_per_session(self, seeded_db):
        """Multiple versioned records for the same session should coexist."""
        for v in range(1, 4):
            seeded_db["db"].add(MedicalRecord(
                id=f"RM{v:03d}",
                patient_id="P001",
                session_id="S001",
                structured_data={"version": v},
                version=v,
                is_final=(v == 3),
                created_by="D001",
            ))
        seeded_db["db"].commit()

        records = (
            seeded_db["db"].query(MedicalRecord)
            .filter_by(session_id="S001")
            .order_by(MedicalRecord.version)
            .all()
        )
        assert len(records) == 3
        assert records[-1].is_final is True
        assert records[-1].version == 3


# ── AuditLog Tests ──────────────────────────────────────────────────────────

class TestAuditLog:
    """Tests for HIPAA audit log entries."""

    def test_audit_log_creation(self, seeded_db):
        audit = AuditLog(
            user_id="D001",
            user_role="doctor",
            action="pipeline_complete",
            resource_type="medical_record",
            resource_id="R001",
            details={"session_id": "S001", "patient_id": "P001"},
            success=True,
        )
        seeded_db["db"].add(audit)
        seeded_db["db"].commit()

        fetched = seeded_db["db"].query(AuditLog).first()
        assert fetched.action == "pipeline_complete"
        assert fetched.success is True
        assert fetched.details["session_id"] == "S001"
