"""
Repository layer — data access separated from business logic.

Each repository encapsulates queries for a single aggregate root.
Services compose repositories; repositories never call each other.
"""

from .patient_repo import PatientRepository
from .record_repo import RecordRepository
from .session_repo import SessionRepository

__all__ = [
    "PatientRepository",
    "RecordRepository",
    "SessionRepository",
]
