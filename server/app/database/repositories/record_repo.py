"""
Record Repository — database queries for MedicalRecord aggregate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.models import MedicalRecord


class RecordRepository:
    """Encapsulates all MedicalRecord-related database queries."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, record_id: str) -> Optional[MedicalRecord]:
        return (
            self.db.query(MedicalRecord)
            .filter(MedicalRecord.id == record_id)
            .first()
        )

    def get_for_patient(
        self,
        patient_id: str,
        limit: Optional[int] = None,
    ) -> List[MedicalRecord]:
        query = (
            self.db.query(MedicalRecord)
            .filter(MedicalRecord.patient_id == patient_id)
            .order_by(MedicalRecord.created_at.desc())
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def count_for_patient(self, patient_id: str) -> int:
        """Return the number of records for a patient (single COUNT query)."""
        return (
            self.db.query(func.count(MedicalRecord.id))
            .filter(MedicalRecord.patient_id == patient_id)
            .scalar() or 0
        )

    def get_for_session(self, session_id: str) -> List[MedicalRecord]:
        return (
            self.db.query(MedicalRecord)
            .filter(MedicalRecord.session_id == session_id)
            .order_by(MedicalRecord.created_at.desc())
            .all()
        )

    def create(self, record: MedicalRecord) -> MedicalRecord:
        self.db.add(record)
        self.db.flush()
        return record

    def update_structured_data(
        self,
        record_id: str,
        structured_data: Dict[str, Any],
    ) -> Optional[MedicalRecord]:
        record = self.get_by_id(record_id)
        if record:
            record.structured_data = structured_data
            self.db.flush()
        return record
