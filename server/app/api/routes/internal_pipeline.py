"""
Internal pipeline route -- called by the Go API gateway pipeline proxy.

This endpoint is NOT exposed to external clients. The Go gateway handles
auth, rate limiting, and Kafka queueing. This route receives the forwarded
request, runs the Python LangGraph pipeline, and returns the result. The
pipeline progress is written to Redis by the PipelineProgressStore so the
Go gateway can serve real-time status to the frontend.

Endpoint:
    POST /internal/pipeline  -- Run the full 18-node LangGraph clinical pipeline.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from app.api.dependencies import get_session_service, get_db
from app.api.schemas import TranscriptSegmentSchema
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["internal"])


class InternalPipelineRequest(BaseModel):
    """Matches the JSON body sent by the Go pipelineproxy handler."""
    session_id: str
    patient_id: str
    doctor_id: str
    is_new_patient: bool = False
    segments: List[TranscriptSegmentSchema] = Field(default_factory=list)


class InternalPipelineResponse(BaseModel):
    session_id: str
    status: str
    clinical_note: Optional[str] = None
    structured_record: Optional[Dict[str, Any]] = None
    clinical_suggestions: Optional[Dict[str, Any]] = None
    validation_report: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


@router.post("/internal/pipeline", response_model=InternalPipelineResponse)
async def run_pipeline_internal(
    body: InternalPipelineRequest,
    db=Depends(get_db),
    service: SessionService = Depends(get_session_service),
):
    """
    Internal-only pipeline endpoint called by the Go Kafka consumer proxy.

    Runs the full 18-node LangGraph clinical pipeline. Progress is written
    to Redis by PipelineProgressStore so the Go gateway can poll it.
    """
    from app.core.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(
        enable_checkpointing=False,
        enable_interrupts=False,
        db_session=db,
    )

    # Pull any OCR-processed documents already stored for this session.
    stored_documents = service.get_documents(body.session_id)
    if stored_documents:
        logger.info(
            "Injecting %d stored OCR document(s) into pipeline for session %s",
            len(stored_documents), body.session_id,
        )

    initial_state = engine.create_initial_state(
        session_id=body.session_id,
        patient_id=body.patient_id,
        doctor_id=body.doctor_id,
        documents=stored_documents,
        inputs={
            "segments": [seg.model_dump() for seg in body.segments],
        },
    )

    initial_state["new_segments"] = [
        {
            "start": seg.start,
            "end": seg.end,
            "speaker": seg.speaker or "Unknown",
            "raw_text": seg.raw_text,
            "confidence": seg.confidence,
        }
        for seg in body.segments
    ]

    if body.is_new_patient:
        initial_state["is_new_patient"] = True

    logger.info(
        "Internal pipeline: running for session %s (%d segments)",
        body.session_id,
        len(body.segments),
    )

    try:
        final_state = await engine.execute_async(initial_state)
        return InternalPipelineResponse(
            session_id=body.session_id,
            status="completed",
            clinical_note=final_state.get("clinical_note"),
            structured_record=final_state.get("structured_record"),
            clinical_suggestions=final_state.get("clinical_suggestions"),
            validation_report=final_state.get("validation_report"),
            message=final_state.get("message", "Pipeline completed"),
        )
    except Exception as exc:
        logger.error(
            "Internal pipeline failed for session %s: %s",
            body.session_id,
            exc,
        )
        return InternalPipelineResponse(
            session_id=body.session_id,
            status="failed",
            message=f"Pipeline failed: {str(exc)}",
        )
