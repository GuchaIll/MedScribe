"""
Session management routes — extracted from main.py.

Endpoints:
    POST /api/session/start                   — Start a new session
    POST /api/session/{session_id}/end        — End a session
    POST /api/session/{session_id}/transcribe — Process a transcription turn
    POST /api/session/{session_id}/pipeline   — Run the full LangGraph pipeline
    POST /api/session/{session_id}/upload     — Upload documents + run OCR pipeline
    GET  /api/session/{session_id}/documents  — List documents for a session
    GET  /api/session/{session_id}/queue      — Get modification review queue
    PATCH /api/session/{session_id}/queue/{item_id} — Update a queue item
"""

import logging
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse

from app.api.dependencies import get_session_service, get_db
from app.api.schemas import (
    SessionStartResponse,
    SessionEndResponse,
    TranscribeRequest,
    TranscribeResponse,
    RunPipelineRequest,
    RunPipelineResponse,
    DocumentProcessingResponse,
    ModificationQueueItemSchema,
    QueueUpdateRequest,
)
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/session", tags=["session"])

# Storage root for uploaded documents
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "storage/uploads"))


@router.post("/start", response_model=SessionStartResponse)
async def start_session(
    service: SessionService = Depends(get_session_service),
):
    return service.start_session()


@router.post("/{session_id}/end", response_model=SessionEndResponse)
async def end_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
):
    return service.end_session(session_id)


@router.post("/{session_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    session_id: str,
    body: TranscribeRequest = TranscribeRequest(),
    service: SessionService = Depends(get_session_service),
):
    return service.process_transcription(
        session_id=session_id,
        text=body.text,
        speaker=body.speaker,
    )


@router.post("/{session_id}/pipeline", response_model=RunPipelineResponse)
async def run_pipeline(
    session_id: str,
    body: RunPipelineRequest,
    db=Depends(get_db),
):
    """
    Run the full 17-node LangGraph clinical pipeline.

    Accepts transcript segments and executes:
      ingest → clean → normalize → segment → extract → evidence →
      fill_record → clinical_suggestions → validate → generate_note →
      persist_results → END.

    Requires a running PostgreSQL + pgvector database.
    """
    from app.core.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(
        enable_checkpointing=True,
        enable_interrupts=False,
        db_session=db,
    )

    # Build initial state from request segments
    initial_state = engine.create_initial_state(
        session_id=body.session_id,
        patient_id=body.patient_id,
        doctor_id=body.doctor_id,
        inputs={
            "segments": [seg.model_dump() for seg in body.segments],
        },
    )

    # Populate new_segments for the pipeline to consume
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

    # Propagate new-patient flag so load_patient_context can skip DB lookups
    if body.is_new_patient:
        initial_state["is_new_patient"] = True

    logger.info("Running pipeline for session %s (%d segments)", session_id, len(body.segments))
    final_state = await engine.execute_async(initial_state)

    return RunPipelineResponse(
        session_id=session_id,
        clinical_note=final_state.get("clinical_note"),
        structured_record=final_state.get("structured_record"),
        clinical_suggestions=final_state.get("clinical_suggestions"),
        validation_report=final_state.get("validation_report"),
        message=final_state.get("message", "Pipeline completed"),
    )


# ── Document upload helpers ─────────────────────────────────────────────────

def _build_document_agent_summary(
    *,
    filename: str,
    doc_type: str,
    field_changes: list,
    conflict_details: list,
    confidence: float,
    page_count: int,
) -> str:
    """
    Build a concise agent summary string describing what OCR extracted.

    Uses LLM if available, otherwise falls back to a deterministic template.
    """
    # ── Deterministic summary (always works, fast) ──────────────────────
    n_fields = len(field_changes)
    n_conflicts = len(conflict_details)
    conf_pct = round(confidence * 100)

    field_bullets = ""
    for fc in field_changes[:10]:
        val_preview = fc["value"][:80] + ("…" if len(fc["value"]) > 80 else "")
        field_bullets += f"  • {fc['field_name']}: {val_preview}\n"
    if len(field_changes) > 10:
        field_bullets += f"  … and {len(field_changes) - 10} more fields\n"

    conflict_bullets = ""
    for cd in conflict_details:
        conflict_bullets += f"  ⚠ {cd['field_name']}: {cd['message']}\n"

    summary = (
        f"Analyzed "{filename}" — classified as {doc_type} "
        f"({page_count} page{'s' if page_count != 1 else ''}, "
        f"{conf_pct}% confidence).\n\n"
    )
    if field_bullets:
        summary += f"Extracted {n_fields} field{'s' if n_fields != 1 else ''}:\n{field_bullets}\n"
    else:
        summary += "No structured fields could be extracted.\n\n"

    if conflict_bullets:
        summary += f"{n_conflicts} conflict{'s' if n_conflicts != 1 else ''} detected:\n{conflict_bullets}"
    else:
        summary += "No conflicts with existing records."

    # ── Try LLM refinement (non-blocking, best-effort) ──────────────────
    try:
        from app.models.llm import LLMClient

        llm = LLMClient()
        prompt = (
            "You are a medical scribe assistant. Summarize the following "
            "document analysis in 2-3 concise sentences for a physician. "
            "Mention the document type, key extracted fields, and any "
            "conflicts. Keep it professional and brief.\n\n"
            f"Document: {filename}\n"
            f"Type: {doc_type}\n"
            f"Pages: {page_count}\n"
            f"Confidence: {conf_pct}%\n"
            f"Fields extracted: {n_fields}\n"
            f"Conflicts: {n_conflicts}\n\n"
            "Field details:\n"
        )
        for fc in field_changes[:8]:
            prompt += f"- {fc['field_name']}: {fc['value'][:100]}\n"
        if conflict_details:
            prompt += "\nConflicts:\n"
            for cd in conflict_details[:5]:
                prompt += f"- {cd['field_name']}: {cd['message']}\n"
        prompt += "\nProvide ONLY the summary, no preamble."

        llm_summary = llm.generate_response(prompt)
        if llm_summary and len(llm_summary.strip()) > 20:
            summary = llm_summary.strip()
    except Exception as e:
        logger.debug("LLM summary generation skipped: %s", e)

    return summary


@router.post("/{session_id}/upload")
async def upload_documents(
    session_id: str,
    files: List[UploadFile] = File(...),
    service: SessionService = Depends(get_session_service),
):
    """
    Upload one or more documents, run the OCR pipeline on each,
    and return structured extraction results + conflict data.

    Files are stored under storage/uploads/{session_id}/.
    Each file is processed through the 10-stage OCR pipeline.
    """
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Resolve patient history for conflict detection
    session_data = service.get_session(session_id)
    patient_history = None
    patient_id = ""
    if session_data:
        patient_id = session_data.get("patient_id", "")
        if patient_id:
            try:
                _, patient_history = service._extract_clinical_context(
                    session_data.get("transcript", [])
                )
            except Exception:
                patient_history = None

    results = []
    for f in files:
        # Store file
        ext = Path(f.filename or "file").suffix
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = session_dir / stored_name

        content = await f.read()
        dest.write_bytes(content)
        logger.info("Uploaded %s (%d bytes) → %s", f.filename, len(content), dest)

        # Run OCR pipeline
        try:
            from app.core.ocr.pipeline import process_document

            ocr_result = await process_document(
                file_path=str(dest),
                session_id=session_id,
                patient_id=patient_id,
                patient_history=patient_history,
                original_filename=f.filename,
            )

            # Build queue items from conflicts
            queue_items = []
            for conflict in ocr_result.conflicts:
                item = {
                    "item_id": conflict.conflict_id,
                    "session_id": session_id,
                    "field_name": conflict.field_name,
                    "extracted_value": conflict.extracted_value,
                    "corrected_value": None,
                    "source_document": conflict.source_document or f.filename,
                    "confidence": 0.0,
                    "conflict_reason": conflict.message,
                    "severity": conflict.severity.value,
                    "status": "pending",
                }
                queue_items.append(item)

            # Also add low-confidence extracted fields to queue
            for field in ocr_result.extracted_fields:
                if field.confidence < 0.5:
                    queue_items.append({
                        "item_id": field.field_id,
                        "session_id": session_id,
                        "field_name": field.field_name,
                        "extracted_value": str(field.value),
                        "corrected_value": None,
                        "source_document": f.filename,
                        "confidence": field.confidence,
                        "conflict_reason": f"Low confidence extraction ({field.confidence:.2f})",
                        "severity": "medium",
                        "status": "pending",
                    })

            # Store queue items in session
            service.add_to_queue(session_id, queue_items)

            # Store document artifact in session for pipeline integration
            if ocr_result.document_artifact:
                service.add_document(session_id, ocr_result.document_artifact)

            # Build structured field change list for agent message
            field_changes = []
            for ef in ocr_result.extracted_fields:
                field_changes.append({
                    "field_name": ef.field_name,
                    "value": str(ef.value) if ef.value else "",
                    "confidence": round(ef.confidence, 2),
                    "category": ef.category.value if hasattr(ef.category, "value") else str(ef.category),
                })

            conflict_details = []
            for c in ocr_result.conflicts:
                conflict_details.append({
                    "field_name": c.field_name,
                    "extracted_value": c.extracted_value,
                    "existing_value": c.existing_value,
                    "severity": c.severity.value,
                    "message": c.message,
                })

            # Generate a short agent summary via LLM
            doc_type_label = (
                ocr_result.classification.doc_type.value.replace("_", " ").title()
                if ocr_result.classification else "Document"
            )
            agent_summary = _build_document_agent_summary(
                filename=f.filename or "document",
                doc_type=doc_type_label,
                field_changes=field_changes,
                conflict_details=conflict_details,
                confidence=ocr_result.overall_confidence,
                page_count=ocr_result.page_count,
            )

            results.append({
                "document_id": ocr_result.document_id,
                "original_name": f.filename,
                "stored_name": stored_name,
                "size": len(content),
                "content_type": f.content_type,
                "path": str(dest),
                "document_type": (
                    ocr_result.classification.doc_type.value
                    if ocr_result.classification else "unknown"
                ),
                "classification_confidence": (
                    ocr_result.classification.confidence
                    if ocr_result.classification else 0.0
                ),
                "overall_confidence": ocr_result.overall_confidence,
                "fields_extracted": len(ocr_result.extracted_fields),
                "conflicts_detected": len(ocr_result.conflicts),
                "queue_items_created": len(queue_items),
                "processing_errors": ocr_result.processing_errors,
                "field_changes": field_changes,
                "conflict_details": conflict_details,
                "agent_summary": agent_summary,
            })

        except Exception as e:
            logger.error("OCR pipeline failed for %s: %s", f.filename, e)
            results.append({
                "original_name": f.filename,
                "stored_name": stored_name,
                "size": len(content),
                "content_type": f.content_type,
                "path": str(dest),
                "error": str(e),
            })

    return JSONResponse(content={
        "session_id": session_id,
        "uploaded": len(results),
        "files": results,
    })


@router.get("/{session_id}/documents")
async def list_documents(
    session_id: str,
    service: SessionService = Depends(get_session_service),
):
    """List all documents and their OCR results for a session."""
    documents = service.get_documents(session_id)
    return JSONResponse(content={
        "session_id": session_id,
        "documents": documents,
    })


@router.get("/{session_id}/queue")
async def get_modification_queue(
    session_id: str,
    service: SessionService = Depends(get_session_service),
):
    """Get all modification queue items for a session."""
    queue = service.get_queue(session_id)
    return JSONResponse(content={
        "session_id": session_id,
        "queue": queue,
        "total": len(queue),
        "pending": sum(1 for q in queue if q.get("status") == "pending"),
    })


@router.patch("/{session_id}/queue/{item_id}")
async def update_queue_item(
    session_id: str,
    item_id: str,
    body: QueueUpdateRequest,
    service: SessionService = Depends(get_session_service),
):
    """Accept, reject, or modify a queue item."""
    updated = service.update_queue_item(
        session_id=session_id,
        item_id=item_id,
        status=body.status,
        corrected_value=body.corrected_value,
    )
    if updated is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Queue item {item_id} not found"},
        )
    return JSONResponse(content=updated)

