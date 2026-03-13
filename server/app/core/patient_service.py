"""
Patient Service for Patient History Management.

Provides methods for:
- Patient profile retrieval
- Historical data aggregation (medications, allergies, diagnoses, labs)
- Clinical context generation
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.database.models import Patient, MedicalRecord


class PatientService:
    """
    Service for managing patient profiles and aggregating historical data.
    """

    def __init__(self, db: Session):
        """
        Initialize patient service.

        Args:
            db: Database session
        """
        self.db = db

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        """
        Get patient by ID.

        Args:
            patient_id: Patient identifier

        Returns:
            Patient model or None if not found
        """
        return self.db.query(Patient).filter(Patient.id == patient_id).first()

    def get_patient_by_mrn(self, mrn: str) -> Optional[Patient]:
        """
        Get patient by Medical Record Number.

        Args:
            mrn: Medical Record Number

        Returns:
            Patient model or None if not found
        """
        return self.db.query(Patient).filter(Patient.mrn == mrn).first()

    def get_patient_records(
        self,
        patient_id: str,
        limit: Optional[int] = None
    ) -> List[MedicalRecord]:
        """
        Get all medical records for a patient.

        Args:
            patient_id: Patient identifier
            limit: Optional limit on number of records

        Returns:
            List of medical records, sorted by date (most recent first)
        """
        query = self.db.query(MedicalRecord).filter(
            MedicalRecord.patient_id == patient_id
        ).order_by(MedicalRecord.created_at.desc())

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_patient_history(self, patient_id: str) -> Dict[str, Any]:
        """
        Get aggregated patient history.

        Args:
            patient_id: Patient identifier

        Returns:
            Dictionary with aggregated patient data
        """
        patient = self.get_patient(patient_id)

        if not patient:
            return {
                "patient_id": patient_id,
                "found": False,
                "error": "Patient not found"
            }

        # Get all records
        records = self.get_patient_records(patient_id)

        # Aggregate data
        return {
            "patient_id": patient_id,
            "found": True,
            "patient_info": {
                "mrn": patient.mrn,
                "full_name": patient.full_name,
                "dob": patient.dob.isoformat() if patient.dob else None,
                "age": patient.age,
                "sex": patient.sex
            },
            "total_visits": len(records),
            "medications": self._aggregate_medications(records),
            "allergies": self._aggregate_allergies(records),
            "diagnoses": self._aggregate_diagnoses(records),
            "labs": self._aggregate_labs(records),
            "procedures": self._aggregate_procedures(records),
            "last_visit": records[0].created_at.isoformat() if records else None,
            "created_at": patient.created_at.isoformat() if patient.created_at else None
        }

    def _aggregate_medications(self, records: List[MedicalRecord]) -> List[Dict[str, Any]]:
        """
        Aggregate and deduplicate medications from records.

        Args:
            records: List of medical records

        Returns:
            List of active medications with most recent information
        """
        medications_map = {}

        for record in reversed(records):  # Process oldest to newest
            structured_data = record.structured_data or {}
            meds = structured_data.get("medications", [])

            if isinstance(meds, list):
                for med in meds:
                    if isinstance(med, dict):
                        med_name = med.get("name", "").lower()
                        if med_name:
                            # Keep most recent entry for each medication
                            medications_map[med_name] = {
                                "name": med.get("name"),
                                "dose": med.get("dose"),
                                "route": med.get("route"),
                                "frequency": med.get("frequency"),
                                "status": med.get("status", "active"),
                                "last_recorded": record.created_at.isoformat()
                            }

        # Return only active medications
        return [
            med for med in medications_map.values()
            if med.get("status") == "active"
        ]

    def _aggregate_allergies(self, records: List[MedicalRecord]) -> List[Dict[str, Any]]:
        """
        Aggregate known allergies from records.

        Args:
            records: List of medical records

        Returns:
            List of allergies with reaction information
        """
        allergies_map = {}

        for record in reversed(records):
            structured_data = record.structured_data or {}
            allergies = structured_data.get("allergies", [])

            if isinstance(allergies, list):
                for allergy in allergies:
                    if isinstance(allergy, dict):
                        substance = allergy.get("substance", "").lower()
                        if substance:
                            allergies_map[substance] = {
                                "substance": allergy.get("substance"),
                                "reaction": allergy.get("reaction"),
                                "severity": allergy.get("severity"),
                                "onset": allergy.get("onset"),
                                "last_recorded": record.created_at.isoformat()
                            }

        return list(allergies_map.values())

    def _aggregate_diagnoses(self, records: List[MedicalRecord]) -> List[Dict[str, Any]]:
        """
        Aggregate diagnoses from records.

        Args:
            records: List of medical records

        Returns:
            List of diagnoses with codes and descriptions
        """
        diagnoses_map = {}

        for record in reversed(records):
            structured_data = record.structured_data or {}
            diagnoses = structured_data.get("diagnoses", [])

            if isinstance(diagnoses, list):
                for diagnosis in diagnoses:
                    if isinstance(diagnosis, dict):
                        code = diagnosis.get("code", "")
                        description = diagnosis.get("description", "")
                        key = f"{code}_{description}".lower()

                        if code or description:
                            diagnoses_map[key] = {
                                "code": diagnosis.get("code"),
                                "description": diagnosis.get("description"),
                                "status": diagnosis.get("status", "active"),
                                "onset_date": diagnosis.get("onset_date"),
                                "first_recorded": diagnoses_map.get(key, {}).get(
                                    "first_recorded",
                                    record.created_at.isoformat()
                                ),
                                "last_recorded": record.created_at.isoformat()
                            }

        return list(diagnoses_map.values())

    def _aggregate_labs(self, records: List[MedicalRecord]) -> List[Dict[str, Any]]:
        """
        Aggregate lab results from records.

        Args:
            records: List of medical records

        Returns:
            List of lab results with values and ranges
        """
        labs = []

        for record in records[:10]:  # Last 10 visits
            structured_data = record.structured_data or {}
            lab_results = structured_data.get("labs", [])

            if isinstance(lab_results, list):
                for lab in lab_results:
                    if isinstance(lab, dict):
                        labs.append({
                            "test_name": lab.get("test_name"),
                            "value": lab.get("value"),
                            "unit": lab.get("unit"),
                            "reference_range": lab.get("reference_range"),
                            "abnormal": lab.get("abnormal", False),
                            "date": record.created_at.isoformat()
                        })

        return labs

    def _aggregate_procedures(self, records: List[MedicalRecord]) -> List[Dict[str, Any]]:
        """
        Aggregate procedures from records.

        Args:
            records: List of medical records

        Returns:
            List of procedures
        """
        procedures = []

        for record in records:
            structured_data = record.structured_data or {}
            procs = structured_data.get("procedures", [])

            if isinstance(procs, list):
                for proc in procs:
                    if isinstance(proc, dict):
                        procedures.append({
                            "name": proc.get("name"),
                            "code": proc.get("code"),
                            "date": proc.get("date") or record.created_at.isoformat(),
                            "notes": proc.get("notes")
                        })

        return procedures

    def get_clinical_context(self, patient_id: str) -> Dict[str, Any]:
        """
        Get clinical context for decision support.

        Args:
            patient_id: Patient identifier

        Returns:
            Clinical context dictionary
        """
        history = self.get_patient_history(patient_id)

        if not history.get("found"):
            return {"error": "Patient not found"}

        # Extract key clinical information
        return {
            "patient_id": patient_id,
            "age": history["patient_info"].get("age"),
            "sex": history["patient_info"].get("sex"),
            "active_medications": history["medications"],
            "known_allergies": history["allergies"],
            "chronic_conditions": [
                d for d in history["diagnoses"]
                if d.get("status") == "active"
            ],
            "recent_labs": history["labs"][:5],  # Last 5 labs
            "total_visits": history["total_visits"]
        }


def get_patient_service(db: Session) -> PatientService:
    """
    Factory function to create patient service.

    Args:
        db: Database session

    Returns:
        PatientService instance
    """
    return PatientService(db)
