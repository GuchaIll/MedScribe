"""
Patient Repository — database queries for Patient aggregate.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.database.models import Patient


class PatientRepository:
    """Encapsulates all Patient-related database queries."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, patient_id: str) -> Optional[Patient]:
        return self.db.query(Patient).filter(Patient.id == patient_id).first()

    def get_by_mrn(self, mrn: str) -> Optional[Patient]:
        return self.db.query(Patient).filter(Patient.mrn == mrn).first()

    def search_by_name(self, name: str, limit: int = 20) -> List[Patient]:
        return (
            self.db.query(Patient)
            .filter(Patient.full_name.ilike(f"%{name}%"))
            .filter(Patient.is_active.is_(True))
            .limit(limit)
            .all()
        )

    def list_active(self, limit: int = 100, offset: int = 0) -> List[Patient]:
        return (
            self.db.query(Patient)
            .filter(Patient.is_active.is_(True))
            .order_by(Patient.full_name)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def create(self, patient: Patient) -> Patient:
        self.db.add(patient)
        self.db.flush()
        return patient

    def update(self, patient: Patient) -> Patient:
        self.db.merge(patient)
        self.db.flush()
        return patient

    def soft_delete(self, patient_id: str) -> bool:
        patient = self.get_by_id(patient_id)
        if patient:
            patient.is_active = False
            self.db.flush()
            return True
        return False
