"""
FastAPI dependencies — injectable services for route handlers.

Centralises dependency wiring so routes stay thin and testable.

NOTE: Database-dependent imports are lazy to avoid triggering the
pydantic_settings → database → config chain at module load time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Generator

from fastapi import Depends

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.core.patient_service import PatientService

from app.services.session_service import SessionService
from app.services.export_service import ExportService
from app.services.transcription_service import TranscriptionService


# ── Singletons (request-independent) ───────────────────────────────────────

@lru_cache(maxsize=1)
def get_session_service() -> SessionService:
    """Single SessionService shared across the app lifetime."""
    return SessionService()


@lru_cache(maxsize=1)
def get_export_service() -> ExportService:
    return ExportService()


@lru_cache(maxsize=1)
def get_transcription_service() -> TranscriptionService:
    return TranscriptionService()


# ── Per-request (depends on DB session) ─────────────────────────────────────

def get_db():
    """Lazy wrapper — defers database import until first request."""
    from app.database.session import get_db as _get_db
    yield from _get_db()


def get_patient_service(db=Depends(get_db)):
    """PatientService is request-scoped because it holds a DB session."""
    from app.core.patient_service import PatientService
    return PatientService(db)
