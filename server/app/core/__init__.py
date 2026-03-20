"""
Core business logic and service layer.
"""

# NOTE: WorkflowEngine is NOT imported here by default to avoid loading heavy dependencies (PyTorch, etc.)
# Import explicitly when needed: from app.core.workflow_engine import WorkflowEngine

from .patient_service import PatientService, get_patient_service
from .clinical_suggestions import ClinicalSuggestionEngine, get_clinical_suggestion_engine
from .record_generator import RecordGenerator, get_record_generator
from .dosage_calculator import DosageCalculator, get_dosage_calculator
from .drug_database_client import DrugDatabaseClient, get_drug_database_client

__all__ = [
    # "WorkflowEngine",  # Import explicitly from workflow_engine module to avoid heavy dependencies
    "PatientService",
    "get_patient_service",
    "ClinicalSuggestionEngine",
    "get_clinical_suggestion_engine",
    "RecordGenerator",
    "get_record_generator",
    "DosageCalculator",
    "get_dosage_calculator",
    "DrugDatabaseClient",
    "get_drug_database_client",
]
