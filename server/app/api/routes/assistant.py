"""
API route — Assistant Q&A endpoint.

POST /api/session/{session_id}/assistant

Accepts a natural-language question from the doctor and returns a grounded
answer retrieved from the patient's medical records (clinical_embeddings,
chunk_embeddings, and MedicalRecord structured data).

Confidence score is included; if below threshold a disclaimer is attached.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import get_db, get_session_service
from app.services.embedding_service import get_embedding_service
from app.database.repositories.record_repo import RecordRepository
from app.models.llm import LLMClient
from app.services.assistant_service import AssistantService
from app.services.session_service import SessionService

router = APIRouter(prefix="/api/session", tags=["assistant"])


# ── Request / response models ─────────────────────────────────────────────────

class AssistantQueryRequest(BaseModel):
    patient_id: str = Field(..., description="Patient ID for the current session")
    question: str = Field(
        ...,
        min_length=3,
        description="Natural-language question from the doctor",
    )


class AssistantQueryResponse(BaseModel):
    answer: str
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Retrieval confidence (0–1). Below 0.65 triggers a disclaimer.",
    )
    low_confidence: bool = Field(
        ...,
        description="True when confidence < 0.65 — disclaimer will be non-null.",
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Shown to the doctor when confidence is below threshold.",
    )
    sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieval sources used to ground the answer.",
    )


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/assistant", response_model=AssistantQueryResponse)
async def query_assistant(
    session_id: str,
    body: AssistantQueryRequest,
    db=Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
):
    """
    Answer a clinical question about a patient using RAG.

    Retrieves grounded context from:
    - Live in-memory session transcript (current session utterances)
    - Live in-memory structured record (incrementally built during session)
    - clinical_embeddings table (is_final=True patient history)
    - chunk_embeddings table (all transcript/document chunks for the patient)
    - MedicalRecord structured_data (latest finalized records)

    Returns an answer with a confidence score. If confidence < 0.65 a
    disclaimer is included. If no data is available the agent admits it.
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    # Pull live in-memory session data (available during an active session before
    # the LangGraph pipeline runs and persists data to pgvector/DB).
    live_session = session_service.get_session(session_id)
    live_transcript = live_session.get("transcript") if live_session else None
    live_structured_record = (
        live_session.get("structured_record") if live_session else None
    )

    embedding_svc = get_embedding_service(db)
    record_repo = RecordRepository(db)

    service = AssistantService(
        embedding_service=embedding_svc,
        record_repo=record_repo,
        llm_factory=lambda: LLMClient(),
        db=db,
    )

    result = service.ask_question(
        patient_id=body.patient_id,
        session_id=session_id,
        question=body.question,
        live_transcript=live_transcript,
        live_structured_record=live_structured_record,
    )

    return AssistantQueryResponse(
        answer=result.answer,
        confidence=result.confidence,
        low_confidence=result.low_confidence,
        disclaimer=result.disclaimer,
        sources=result.sources,
    )
