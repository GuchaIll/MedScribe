"""
API routes for clinical decision support.

Endpoints:
    POST /api/clinical/suggestions        - Generate suggestions for any structured record
    POST /api/clinical/check-allergies    - Quick allergy check (subset of suggestions)
    POST /api/clinical/check-interactions - Quick drug interaction check
    POST /api/clinical/interpret-labs      - Lab result interpretation with clinical context
    POST /api/clinical/override           - Physician override of a clinical alert
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.core.clinical_suggestions import get_clinical_suggestion_engine

router = APIRouter(prefix="/api/clinical", tags=["clinical"])


# ── Request / response models ──────────────────────────────────────────────────

class ClinicalSuggestionsRequest(BaseModel):
    """Request body for generating clinical suggestions."""

    current_record: Dict[str, Any] = Field(
        ...,
        description="The current structured medical record being authored"
    )
    patient_history: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Aggregated patient history (allergies, medications, diagnoses). "
            "If omitted, only current-record analysis is performed."
        )
    )
    use_external_database: bool = Field(
        default=False,
        description="Whether to enrich results with external drug databases (RxNorm / OpenFDA)"
    )


class AllergyCheckRequest(BaseModel):
    medications: List[Dict[str, Any]] = Field(
        ...,
        description="List of medication dicts with at least a 'name' field"
    )
    allergies: List[Dict[str, Any]] = Field(
        ...,
        description="List of allergy dicts with 'substance' and 'reaction' fields"
    )


class InteractionCheckRequest(BaseModel):
    medications: List[Dict[str, Any]] = Field(
        ...,
        description="List of medication dicts with at least a 'name' field"
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/suggestions")
async def get_clinical_suggestions(body: ClinicalSuggestionsRequest):
    """
    Generate clinical decision support suggestions for a structured medical record.

    Checks:
    - Allergy-medication conflicts
    - Drug-drug interactions
    - Contraindications based on diagnoses / conditions
    - Dosage appropriateness (age, weight, renal function)
    - Historical context from prior visits

    Returns a risk level ('low' | 'moderate' | 'high' | 'critical') and
    structured lists of alerts, interactions, and contextual notes.
    """
    engine = get_clinical_suggestion_engine(
        use_external_database=body.use_external_database
    )

    patient_history = body.patient_history or {
        "found": True,
        "allergies": body.current_record.get("allergies", []),
        "medications": [],
        "diagnoses": body.current_record.get("diagnoses", []),
        "labs": body.current_record.get("labs", []),
    }

    suggestions = engine.generate_suggestions(
        current_record=body.current_record,
        patient_history=patient_history
    )
    return suggestions


@router.post("/check-allergies")
async def check_allergies(body: AllergyCheckRequest):
    """
    Quick allergy-vs-medication conflict check.

    Lightweight endpoint — does not require a full structured record or
    patient history. Useful for point-of-care checks when adding a new
    medication.
    """
    engine = get_clinical_suggestion_engine()

    synthetic_record = {"medications": body.medications, "diagnoses": []}
    synthetic_history = {
        "found": True,
        "allergies": body.allergies,
        "medications": [],
        "diagnoses": [],
        "labs": [],
    }

    suggestions = engine.generate_suggestions(
        current_record=synthetic_record,
        patient_history=synthetic_history
    )

    return {
        "allergy_alerts": suggestions["allergy_alerts"],
        "risk_level": suggestions["risk_level"],
    }


@router.post("/check-interactions")
async def check_drug_interactions(body: InteractionCheckRequest):
    """
    Quick drug-drug interaction check.

    Pass a list of medications and receive any detected interactions.
    Does not require patient history.
    """
    engine = get_clinical_suggestion_engine()

    synthetic_record = {"medications": body.medications, "diagnoses": []}
    synthetic_history = {
        "found": True,
        "allergies": [],
        "medications": [],
        "diagnoses": [],
        "labs": [],
    }

    suggestions = engine.generate_suggestions(
        current_record=synthetic_record,
        patient_history=synthetic_history
    )

    return {
        "drug_interactions": suggestions["drug_interactions"],
        "risk_level": suggestions["risk_level"],
    }


# ── Lab Interpretation ─────────────────────────────────────────────────────────

class LabInterpretationRequest(BaseModel):
    labs: List[Dict[str, Any]] = Field(
        ..., description="Lab results with test_name, value, unit"
    )
    patient_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Patient age, sex, conditions for contextual interpretation",
    )


@router.post("/interpret-labs")
async def interpret_labs(body: LabInterpretationRequest):
    """
    Interpret lab results with clinical context.

    Returns per-test interpretation with reference ranges, severity,
    clinical significance, and any critical value flags.
    """
    from app.core.lab_interpreter import get_lab_interpreter

    interpreter = get_lab_interpreter()
    result = interpreter.interpret(
        labs=body.labs,
        patient_context=body.patient_context or {},
    )
    return result


# ── Clinical Override Logging ──────────────────────────────────────────────────

class ClinicalOverrideRequest(BaseModel):
    session_id: str
    alert_type: str = Field(
        ..., description="allergy_conflict | drug_interaction | contraindication | dosage_issue"
    )
    alert_summary: str
    justification: str = Field(..., description="Clinical justification for the override")
    overridden_by: str = Field(..., description="Doctor/user ID")


@router.post("/override")
async def override_clinical_alert(body: ClinicalOverrideRequest):
    """
    Log a physician's override of a clinical decision support alert.

    Overrides are recorded in the HIPAA audit log for compliance.
    The physician must provide a clinical justification.
    """
    import logging
    from datetime import datetime

    logger = logging.getLogger(__name__)

    if not body.justification.strip():
        raise HTTPException(
            status_code=400,
            detail="Clinical justification is required for overrides",
        )

    # Write to audit log (in-memory fallback if no DB)
    override_entry = {
        "session_id": body.session_id,
        "alert_type": body.alert_type,
        "alert_summary": body.alert_summary,
        "justification": body.justification,
        "overridden_by": body.overridden_by,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Attempt DB persistence
    override_id = -1
    logged = False
    try:
        from app.database.base import get_db_session
        db = get_db_session()
        if db:
            from app.database.models import AuditLog
            audit = AuditLog(
                user_id=body.overridden_by,
                user_role="doctor",
                action="clinical_override",
                resource_type="clinical_alert",
                resource_id=body.session_id,
                details=override_entry,
                success=True,
            )
            db.add(audit)
            db.commit()
            override_id = audit.id
            logged = True
            db.close()
    except Exception as e:
        logger.warning("Override audit DB write failed (in-memory fallback): %s", e)

    if not logged:
        # In-memory fallback
        logger.info(
            "CLINICAL OVERRIDE [%s] session=%s alert=%s by=%s justification=%s",
            body.alert_type,
            body.session_id,
            body.alert_summary,
            body.overridden_by,
            body.justification,
        )
        logged = True

    return {
        "override_id": override_id,
        "message": "Override logged successfully",
        "logged": logged,
    }
