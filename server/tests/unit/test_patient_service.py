"""
Unit tests for patient_service.py (simplified version)
"""

import pytest
from datetime import datetime, timedelta
from app.core.patient_service import PatientService, get_patient_service
from app.database.models import Patient, MedicalRecord


@pytest.mark.unit
@pytest.mark.db
class TestPatientService:
    """Tests for PatientService class."""

    @pytest.fixture
    def patient_service(self, db_session):
        """Create a patient service instance."""
        return PatientService(db_session)

    def test_get_patient_by_id(self, patient_service, sample_patient):
        """Test retrieving patient by ID."""
        patient = patient_service.get_patient(sample_patient.id)

        assert patient is not None
        assert patient.id == sample_patient.id
        assert patient.mrn == sample_patient.mrn

    def test_get_patient_not_found(self, patient_service):
        """Test retrieving nonexistent patient."""
        patient = patient_service.get_patient("NONEXISTENT")

        assert patient is None

    def test_get_patient_by_mrn(self, patient_service, sample_patient):
        """Test retrieving patient by MRN."""
        patient = patient_service.get_patient_by_mrn(sample_patient.mrn)

        assert patient is not None
        assert patient.mrn == sample_patient.mrn
        assert patient.id == sample_patient.id

    def test_get_patient_records(self, patient_service, sample_patient, sample_medical_record):
        """Test retrieving patient records."""
        records = patient_service.get_patient_records(sample_patient.id)

        assert len(records) > 0
        assert records[0].patient_id == sample_patient.id

    def test_get_patient_records_empty(self, patient_service, db_session):
        """Test retrieving records for patient with no records."""
        # Create patient with no records
        patient = Patient(
            id="PAT_EMPTY",
            mrn="MRN_EMPTY",
            full_name="Empty Patient",
            dob=datetime(1990, 1, 1),
            sex="F"
        )
        db_session.add(patient)
        db_session.commit()

        records = patient_service.get_patient_records(patient.id)

        assert len(records) == 0

    def test_get_patient_history_basic(self, patient_service, sample_patient, sample_medical_record):
        """Test retrieving basic patient history."""
        history = patient_service.get_patient_history(sample_patient.id)

        assert history["found"] is True
        assert history["patient_id"] == sample_patient.id
        assert "patient_info" in history
        assert "medications" in history
        assert "allergies" in history
        assert "diagnoses" in history

    def test_get_patient_history_not_found(self, patient_service):
        """Test retrieving history for nonexistent patient."""
        history = patient_service.get_patient_history("NONEXISTENT")

        assert history["found"] is False
        assert "error" in history

    def test_get_clinical_context(self, patient_service, sample_patient, sample_medical_record):
        """Test retrieving clinical context for decision support."""
        context = patient_service.get_clinical_context(sample_patient.id)

        assert context["patient_id"] == sample_patient.id
        assert "age" in context
        assert "sex" in context
        assert "active_medications" in context
        assert "known_allergies" in context

    def test_get_clinical_context_not_found(self, patient_service):
        """Test getting clinical context for nonexistent patient."""
        context = patient_service.get_clinical_context("NONEXISTENT")

        assert "error" in context


@pytest.mark.unit
class TestGetPatientService:
    """Tests for get_patient_service factory function."""

    def test_get_patient_service_creates_service(self, db_session):
        """Test that factory function creates service."""
        service = get_patient_service(db_session)

        assert isinstance(service, PatientService)
        assert service.db == db_session
