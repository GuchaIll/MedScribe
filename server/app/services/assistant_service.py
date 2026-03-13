"""
AssistantService — RAG-based medical Q&A agent.

Triggered when the doctor says "Assistant, <question>" during a live session.
Retrieves grounded context from:
  - clinical_embeddings (all is_final=True patient history)
  - chunk_embeddings (transcript/document chunks across all patient sessions)
  - MedicalRecord structured_data (latest finalized records)

Confidence is computed from retrieval similarity scores.
If confidence < CONFIDENCE_THRESHOLD (0.65), a disclaimer is shown.
If no context is found at all, the agent admits the data is unavailable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session as DBSession

from app.services.embedding_service import EmbeddingService
from app.database.repositories.record_repo import RecordRepository
from app.models.llm import LLMClient

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.65
TOP_K = 6
RETRIEVAL_FLOOR = 0.30  # Minimum cosine similarity to include a result


@dataclass
class AssistantResponse:
    answer: str
    confidence: float
    low_confidence: bool
    disclaimer: Optional[str]
    sources: List[Dict[str, Any]] = field(default_factory=list)


# ── Prompt template ──────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """You are a medical assistant with access to a patient's electronic health records.
Answer ONLY using the patient records provided below.
If the information is not present in the records, say exactly:
"I don't have that information in the patient's records."
Do NOT invent medications, diagnoses, lab values, or any other clinical data.
Be concise but complete. Cite which section of the records your answer comes from.

--- STRUCTURED MEDICAL RECORDS ---
{structured_records}

--- CLINICAL FACTS FROM PATIENT HISTORY ---
{clinical_facts}

--- RELEVANT TRANSCRIPT / DOCUMENT EXCERPTS ---
{chunk_excerpts}

--- DOCTOR'S QUESTION ---
{question}

--- YOUR ANSWER ---"""


class AssistantService:
    """
    RAG-based Q&A agent grounded in the patient's medical records.

    Usage:
        svc = AssistantService(embedding_service, record_repo, llm_factory, db)
        response = svc.ask_question(patient_id, session_id, question, doctor_id)
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        record_repo: RecordRepository,
        llm_factory: Callable[[], LLMClient],
        db: DBSession,
    ) -> None:
        self.embedding_service = embedding_service
        self.record_repo = record_repo
        self.llm_factory = llm_factory
        self.db = db

    # ── Public API ───────────────────────────────────────────────────────────

    def ask_question(
        self,
        patient_id: str,
        session_id: str,
        question: str,
        doctor_id: str = "",
    ) -> AssistantResponse:
        """
        Answer a clinical question about a patient using RAG.

        Steps:
        1. Embed the question.
        2. Retrieve relevant clinical facts (clinical_embeddings, is_final=True).
        3. Retrieve relevant transcript/document chunks (chunk_embeddings across
           all sessions for this patient).
        4. Fetch latest finalized MedicalRecord structured data.
        5. Compute confidence from retrieval scores.
        6. If no context: admit unavailability without calling LLM.
        7. Build grounded prompt and call LLM.
        8. Attach disclaimer if confidence < threshold.
        """
        logger.info(
            "Assistant query — patient=%s session=%s question=%r",
            patient_id,
            session_id,
            question[:80],
        )

        # 1. Embed question
        try:
            query_vec = self.embedding_service.embed_text(question)
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            return self._unavailable_response(
                "I was unable to process your question at this time."
            )

        # 2. Clinical facts (cross-visit, is_final=True)
        clinical_results = self._retrieve_clinical_facts(patient_id, query_vec)

        # 3. Chunk embeddings (all sessions for this patient)
        chunk_results = self._retrieve_chunks_for_patient(patient_id, query_vec)

        # 4. Structured records (latest 3 finalized)
        structured_records = self._retrieve_structured_records(patient_id)

        # 5. Confidence
        all_scores = [r["similarity"] for r in clinical_results + chunk_results]
        confidence = _compute_confidence(all_scores)

        # 6. No context at all → admit unavailability
        if not all_scores and not structured_records:
            return self._unavailable_response(
                "I don't have sufficient information in this patient's records "
                "to answer that question. Please consult the full chart."
            )

        # 7. Build prompt and call LLM
        prompt = _PROMPT_TEMPLATE.format(
            structured_records=_format_structured_records(structured_records),
            clinical_facts=_format_clinical_facts(clinical_results),
            chunk_excerpts=_format_chunks(chunk_results),
            question=question,
        )

        try:
            llm = self.llm_factory()
            answer = llm.generate_response(prompt)
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return self._unavailable_response(
                "I was unable to generate a response at this time. "
                "Please consult the patient's chart directly."
            )

        # 8. Disclaimer if low confidence
        low_confidence = confidence < CONFIDENCE_THRESHOLD
        disclaimer: Optional[str] = None
        if low_confidence:
            pct = int(round(confidence * 100))
            disclaimer = (
                f"Confidence score: {pct}%. "
                "This answer is based on partial or low-similarity data — "
                "please verify against the full patient record before acting."
            )

        # Build sources list for UI
        sources = _build_sources(clinical_results, chunk_results)

        return AssistantResponse(
            answer=answer.strip(),
            confidence=round(confidence, 4),
            low_confidence=low_confidence,
            disclaimer=disclaimer,
            sources=sources,
        )

    # ── Retrieval helpers ────────────────────────────────────────────────────

    def _retrieve_clinical_facts(
        self, patient_id: str, query_vec: np.ndarray
    ) -> List[Dict[str, Any]]:
        """pgvector search against clinical_embeddings for this patient."""
        try:
            return self.embedding_service.search_patient_facts(
                patient_id=patient_id,
                query_embedding=query_vec,
                top_k=TOP_K,
                threshold=RETRIEVAL_FLOOR,
                only_final=True,
            )
        except Exception as exc:
            logger.warning("Clinical fact retrieval failed: %s", exc)
            return []

    def _retrieve_chunks_for_patient(
        self, patient_id: str, query_vec: np.ndarray
    ) -> List[Dict[str, Any]]:
        """
        pgvector search against chunk_embeddings joined to sessions,
        scoped to all sessions belonging to this patient.
        """
        if self.db is None:
            return []

        try:
            query_list = query_vec.tolist()
            result = self.db.execute(
                sql_text("""
                    SELECT ce.chunk_text, ce.source_type,
                           1 - (ce.embedding <=> :query_vec) AS similarity
                    FROM chunk_embeddings ce
                    JOIN sessions s ON s.id = ce.session_id
                    WHERE s.patient_id = :patient_id
                      AND (1 - (ce.embedding <=> :query_vec)) >= :threshold
                    ORDER BY ce.embedding <=> :query_vec
                    LIMIT :top_k
                """),
                {
                    "query_vec": str(query_list),
                    "patient_id": patient_id,
                    "threshold": RETRIEVAL_FLOOR,
                    "top_k": TOP_K,
                },
            )
            return [
                {
                    "chunk_text": row.chunk_text,
                    "source_type": row.source_type,
                    "similarity": float(row.similarity),
                }
                for row in result
            ]
        except Exception as exc:
            logger.warning("Chunk retrieval failed: %s", exc)
            return []

    def _retrieve_structured_records(
        self, patient_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch the latest finalized MedicalRecords for this patient."""
        try:
            records = self.record_repo.get_for_patient(patient_id, limit=3)
            finalized = [r for r in records if r.is_final and r.structured_data]
            if not finalized:
                # Fall back to any record if no finalized ones exist
                finalized = [r for r in records if r.structured_data]
            return [r.structured_data for r in finalized[:3]]
        except Exception as exc:
            logger.warning("Structured record retrieval failed: %s", exc)
            return []

    # ── Static helper ────────────────────────────────────────────────────────

    @staticmethod
    def _unavailable_response(message: str) -> AssistantResponse:
        return AssistantResponse(
            answer=message,
            confidence=0.0,
            low_confidence=True,
            disclaimer=None,
            sources=[],
        )


# ── Private formatting helpers ───────────────────────────────────────────────

def _compute_confidence(scores: List[float]) -> float:
    """
    Weighted harmonic mean favoring top results.
    Returns 0.0 if scores is empty.
    """
    if not scores:
        return 0.0
    if len(scores) == 1:
        return scores[0]
    sorted_scores = sorted(scores, reverse=True)
    weights = [1.0 / (i + 1) for i in range(len(sorted_scores))]
    return sum(s * w for s, w in zip(sorted_scores, weights)) / sum(weights)


def _format_structured_records(records: List[Dict[str, Any]]) -> str:
    if not records:
        return "No finalized structured records available."
    parts = []
    for i, rec in enumerate(records, start=1):
        parts.append(f"[Record {i}]")
        for key in (
            "patient", "allergies", "medications", "diagnoses",
            "vitals", "labs", "procedures", "followups",
        ):
            value = rec.get(key)
            if value:
                parts.append(f"  {key.upper()}: {json.dumps(value, default=str)}")
    return "\n".join(parts) if parts else "No data."


def _format_clinical_facts(facts: List[Dict[str, Any]]) -> str:
    if not facts:
        return "No clinical facts retrieved."
    lines = []
    for f in facts:
        fact_type = f.get("fact_type", "unknown")
        fact_data = f.get("fact_data") or {}
        similarity = f.get("similarity", 0.0)
        lines.append(
            f"- [{fact_type}] {json.dumps(fact_data, default=str)} "
            f"(similarity: {similarity:.2f})"
        )
    return "\n".join(lines)


def _format_chunks(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return "No transcript/document excerpts retrieved."
    lines = []
    for c in chunks:
        source = c.get("source_type", "unknown")
        similarity = c.get("similarity", 0.0)
        text = c.get("chunk_text", "").strip()
        lines.append(f"- [{source}] ({similarity:.2f}): {text}")
    return "\n".join(lines)


def _build_sources(
    clinical: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    sources = []
    for f in clinical:
        sources.append({
            "type": "clinical_fact",
            "fact_type": f.get("fact_type"),
            "snippet": json.dumps(f.get("fact_data") or {}, default=str)[:120],
            "similarity": round(f.get("similarity", 0.0), 3),
        })
    for c in chunks:
        sources.append({
            "type": c.get("source_type", "chunk"),
            "snippet": (c.get("chunk_text") or "")[:120],
            "similarity": round(c.get("similarity", 0.0), 3),
        })
    return sources
