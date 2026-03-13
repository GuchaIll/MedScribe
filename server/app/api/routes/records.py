"""
API routes for medical record generation and export.

Endpoints:
    POST /api/records/generate               - Generate record HTML from structured data
    POST /api/records/preview                - HTML preview in browser
    POST /api/records/regenerate             - Regenerate with physician feedback
    POST /api/records/commit                 - Finalize a physician-reviewed record
    GET  /api/records/patient/{id}/history   - Record version history for a patient
    GET  /api/records/templates              - List available templates
"""

import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.core.record_generator import get_record_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records", tags=["records"])

AVAILABLE_TEMPLATES = ["soap", "discharge", "consultation", "progress"]


# ── Request / response models ──────────────────────────────────────────────────

class GenerateRecordRequest(BaseModel):
    """Request body for generating a medical record."""

    record: Dict[str, Any] = Field(
        ...,
        description="Structured medical record (StructuredRecord-compatible dict)"
    )
    template: str = Field(
        default="soap",
        description="Template name: soap | discharge | consultation | progress"
    )
    clinical_suggestions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional clinical suggestions to embed in the record"
    )
    format: str = Field(
        default="html",
        description="Output format: html | pdf | text"
    )


class TemplateInfo(BaseModel):
    name: str
    description: str
    formats: List[str]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_template(template: str) -> None:
    if template not in AVAILABLE_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template '{template}'. Available: {AVAILABLE_TEMPLATES}"
        )


def _validate_format(fmt: str) -> None:
    if fmt not in ("html", "pdf", "text"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{fmt}'. Supported: html, pdf, text"
        )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=List[TemplateInfo])
async def list_templates():
    """List all available record templates and their supported output formats."""
    return [
        TemplateInfo(
            name="soap",
            description="SOAP Note — Subjective, Objective, Assessment, Plan",
            formats=["html", "pdf", "text"]
        ),
        TemplateInfo(
            name="discharge",
            description="Discharge Summary — inpatient discharge documentation",
            formats=["html", "pdf", "text"]
        ),
        TemplateInfo(
            name="consultation",
            description="Consultation Note — specialist referral documentation",
            formats=["html", "pdf", "text"]
        ),
        TemplateInfo(
            name="progress",
            description="Progress Note — follow-up visit documentation",
            formats=["html", "pdf", "text"]
        ),
    ]


@router.post("/generate")
async def generate_record(body: GenerateRecordRequest):
    """
    Generate a formatted medical record from structured data.

    Returns HTML, PDF bytes, or plain text depending on the requested format.
    PDF requires WeasyPrint to be installed; falls back to HTML if unavailable.
    """
    _validate_template(body.template)
    _validate_format(body.format)

    generator = get_record_generator()

    if body.format == "pdf":
        content = generator.generate_pdf(
            body.record, body.template, body.clinical_suggestions
        )
        media_type = "application/pdf"
        if content[:4] != b"%PDF":
            # WeasyPrint not installed — returned HTML instead
            media_type = "text/html; charset=utf-8"
        return Response(content=content, media_type=media_type)

    if body.format == "text":
        text = generator.generate_text(body.record, body.template)
        return Response(content=text, media_type="text/plain; charset=utf-8")

    # Default: html
    html = generator.generate(body.record, body.template, body.clinical_suggestions)
    return HTMLResponse(content=html)


@router.post("/preview", response_class=HTMLResponse)
async def preview_record(body: GenerateRecordRequest):
    """
    Generate an HTML preview of a medical record (browser-friendly).

    Identical to POST /generate with format=html but always returns HTML.
    """
    _validate_template(body.template)

    generator = get_record_generator()
    html = generator.generate(body.record, body.template, body.clinical_suggestions)
    return HTMLResponse(content=html)


# ── Regeneration with feedback ─────────────────────────────────────────────────

class RegenerateRecordRequest(BaseModel):
    """Request to regenerate a record with physician feedback."""
    record: Dict[str, Any] = Field(..., description="Current structured record")
    template: str = Field(default="soap")
    clinical_suggestions: Optional[Dict[str, Any]] = None
    feedback: str = Field(..., description="Physician feedback to incorporate")
    format: str = Field(default="html")
    iteration: int = Field(default=1)


@router.post("/regenerate")
async def regenerate_record(body: RegenerateRecordRequest):
    """
    Regenerate a medical record incorporating physician feedback.

    Uses the LLM to apply the physician's corrections/feedback to the
    structured record, then renders the updated record via the template
    engine.  Returns the new HTML along with a diff summary.
    """
    _validate_template(body.template)
    _validate_format(body.format)

    generator = get_record_generator()

    # Apply feedback via LLM to update structured record
    updated_record = await _apply_feedback_to_record(
        body.record, body.feedback, body.template
    )

    if body.format == "pdf":
        content = generator.generate_pdf(
            updated_record, body.template, body.clinical_suggestions
        )
        return Response(content=content, media_type="application/pdf")

    if body.format == "text":
        text = generator.generate_text(updated_record, body.template)
        return Response(content=text, media_type="text/plain; charset=utf-8")

    html = generator.generate(
        updated_record, body.template, body.clinical_suggestions
    )

    return {
        "html": html,
        "updated_record": updated_record,
        "iteration": body.iteration + 1,
        "feedback_applied": body.feedback,
    }


async def _apply_feedback_to_record(
    record: Dict[str, Any],
    feedback: str,
    template_name: str,
) -> Dict[str, Any]:
    """
    Use LLM to incorporate physician feedback into the structured record.

    Falls back to returning the record unchanged if LLM is unavailable.
    """
    import copy
    import json as json_mod

    updated = copy.deepcopy(record)

    try:
        from app.config.llm import get_llm_client
        client = get_llm_client()
        if client is None:
            raise ImportError("No LLM client available")

        prompt = (
            "You are a medical record editor. Given the current structured "
            "medical record (JSON) and the physician's feedback, update the "
            "record to incorporate the corrections. Return ONLY the updated "
            "JSON — preserve the exact same schema and field names.\n\n"
            f"CURRENT RECORD:\n```json\n{json_mod.dumps(record, indent=2, default=str)}\n```\n\n"
            f"PHYSICIAN FEEDBACK:\n{feedback}\n\n"
            "UPDATED RECORD (JSON only):"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()

        # Extract JSON from response (may be wrapped in ```json ... ```)
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0]

        updated = json_mod.loads(raw)
        logger.info("Successfully applied physician feedback via LLM")

    except Exception as e:
        logger.warning("LLM feedback application failed (%s), returning original record", e)

    return updated


# ── Record Commit (Finalize) ───────────────────────────────────────────────────

class RecordCommitRequest(BaseModel):
    session_id: str
    record_id: str
    corrections: Optional[Dict[str, Any]] = None
    template: str = Field(default="soap")
    finalized_by: str = Field(..., description="Doctor/user ID")


@router.post("/commit")
async def commit_record(body: RecordCommitRequest):
    """
    Finalize a physician-reviewed medical record.

    Marks the record as ``is_final=True``, increments the version if
    corrections are provided, records the finalization timestamp, and
    writes a HIPAA audit trail entry.
    """
    try:
        from app.database.base import get_db_session
        db = get_db_session()
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        from app.database.models import MedicalRecord, AuditLog

        record = db.query(MedicalRecord).filter(
            MedicalRecord.id == body.record_id
        ).first()

        if not record:
            # Create a minimal record if pipeline ran in-memory
            record = MedicalRecord(
                id=body.record_id or str(uuid.uuid4()),
                patient_id="",
                session_id=body.session_id,
                structured_data=body.corrections or {},
                version=1,
                is_final=False,
                record_type=body.template.upper(),
                created_by=body.finalized_by,
            )
            db.add(record)

        # Apply corrections
        if body.corrections:
            record.structured_data = {
                **(record.structured_data or {}),
                **body.corrections,
            }
            record.version = (record.version or 0) + 1

        record.is_final = True
        record.finalized_at = datetime.utcnow()
        record.finalized_by = body.finalized_by
        record.template_used = body.template

        # Audit log
        audit = AuditLog(
            user_id=body.finalized_by,
            user_role="doctor",
            action="record_finalized",
            resource_type="medical_record",
            resource_id=record.id,
            details={
                "session_id": body.session_id,
                "version": record.version,
                "had_corrections": body.corrections is not None,
            },
            success=True,
        )
        db.add(audit)
        db.commit()

        logger.info(
            "Record %s finalized (v%d) by %s",
            record.id, record.version, body.finalized_by,
        )

        return {
            "record_id": record.id,
            "version": record.version,
            "is_final": True,
            "message": f"Record finalized as version {record.version}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Record commit failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Record Version History ─────────────────────────────────────────────────────

@router.get("/patient/{patient_id}/history")
async def get_patient_record_history(
    patient_id: str,
    limit: int = Query(default=20, le=100),
):
    """
    Return all medical record versions for a patient, newest first.

    Useful for longitudinal review and audit.
    """
    try:
        from app.database.base import get_db_session
        db = get_db_session()
        if db is None:
            return {"patient_id": patient_id, "records": [], "message": "Database not available"}

        from app.database.models import MedicalRecord

        records = (
            db.query(MedicalRecord)
            .filter(MedicalRecord.patient_id == patient_id)
            .order_by(MedicalRecord.created_at.desc())
            .limit(limit)
            .all()
        )

        history = []
        for r in records:
            history.append({
                "record_id": r.id,
                "session_id": r.session_id,
                "version": r.version,
                "is_final": r.is_final,
                "confidence_score": r.confidence_score,
                "record_type": r.record_type,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
                "finalized_by": r.finalized_by,
            })

        db.close()

        return {
            "patient_id": patient_id,
            "total": len(history),
            "records": history,
        }

    except Exception as e:
        logger.warning("Failed to retrieve record history: %s", e)
        return {"patient_id": patient_id, "records": [], "error": str(e)}
