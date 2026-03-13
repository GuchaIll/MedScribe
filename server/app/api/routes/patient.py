"""
Patient API Routes.

Provides longitudinal patient view endpoints:
  - GET /api/patient/{id}/profile     Full profile with trends, risk, timeline
  - GET /api/patient/{id}/lab-trends  Lab value trend analysis
  - GET /api/patient/{id}/risk-score  Current composite risk score
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import PatientProfileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patient", tags=["patient"])


# ── GET /api/patient/{patient_id}/profile ────────────────────────────────

@router.get("/{patient_id}/profile")
async def get_patient_profile(patient_id: str):
    """
    Build a full longitudinal profile for a patient.

    Aggregates lab trends, medication timeline, and risk score
    across all historical records.
    """
    patient_info, records = _load_patient_data(patient_id)

    from app.core.patient_model import PatientModel

    profile = PatientModel.build_patient_profile(
        patient_info=patient_info,
        records=records,
    )

    return profile


# ── GET /api/patient/{patient_id}/lab-trends ─────────────────────────────

@router.get("/{patient_id}/lab-trends")
async def get_lab_trends(
    patient_id: str,
    test_name: Optional[str] = Query(None, description="Filter by test name"),
):
    """
    Return lab trend analysis for a patient.

    Optionally filter to a single test name.
    """
    patient_info, records = _load_patient_data(patient_id)

    # Flatten all labs from records
    all_labs = []
    for rec in records:
        for lab in rec.get("labs", []):
            if isinstance(lab, dict):
                all_labs.append(lab)

    from app.core.patient_model import PatientModel

    trends = PatientModel.compute_lab_trends(all_labs)

    if test_name:
        test_lower = test_name.lower()
        trends = [t for t in trends if t["test_name"].lower() == test_lower]

    return {"patient_id": patient_id, "trends": trends}


# ── GET /api/patient/{patient_id}/risk-score ─────────────────────────────

@router.get("/{patient_id}/risk-score")
async def get_risk_score(patient_id: str):
    """
    Compute a current composite risk score for the patient.
    """
    patient_info, records = _load_patient_data(patient_id)

    all_diagnoses = []
    all_meds = []
    all_labs = []
    for rec in records:
        for dx in rec.get("diagnoses", []):
            if isinstance(dx, dict):
                all_diagnoses.append(dx)
        for med in rec.get("medications", []):
            if isinstance(med, dict):
                all_meds.append(med)
        for lab in rec.get("labs", []):
            if isinstance(lab, dict):
                all_labs.append(lab)

    from app.core.patient_model import PatientModel

    risk = PatientModel.compute_risk_score(
        patient_info=patient_info,
        diagnoses=all_diagnoses,
        medications=all_meds,
        labs=all_labs,
        visit_count=len(records),
    )

    return {"patient_id": patient_id, "risk": risk}


# ── Internal helpers ─────────────────────────────────────────────────────

def _load_patient_data(patient_id: str):
    """
    Load patient info + structured-data records.

    Tries DB first, falls back to empty data so the endpoints
    still return a structure even when the DB is unavailable.
    """
    patient_info = {"patient_id": patient_id}
    records = []

    try:
        from app.database.base import get_db_session

        db = get_db_session()
        if db is not None:
            from app.database.models import Patient, MedicalRecord

            patient = db.query(Patient).filter(Patient.id == patient_id).first()
            if patient:
                patient_info = {
                    "patient_id": patient.id,
                    "mrn": patient.mrn,
                    "full_name": patient.full_name,
                    "dob": patient.dob.isoformat() if patient.dob else None,
                    "age": patient.age,
                    "sex": patient.sex,
                }

            db_records = (
                db.query(MedicalRecord)
                .filter(MedicalRecord.patient_id == patient_id)
                .order_by(MedicalRecord.created_at.desc())
                .limit(50)
                .all()
            )
            records = [r.structured_data or {} for r in db_records]
            db.close()

    except Exception as e:
        logger.warning("Patient data load from DB failed: %s", e)

    return patient_info, records
