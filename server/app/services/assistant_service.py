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

# Lazy imports to avoid circular dependencies -- resolved at runtime
_HybridRetrievalService = None
_IterativeRetrievalService = None


def _get_hybrid_class():
    global _HybridRetrievalService
    if _HybridRetrievalService is None:
        from app.services.hybrid_retrieval import HybridRetrievalService
        _HybridRetrievalService = HybridRetrievalService
    return _HybridRetrievalService


def _get_iterative_class():
    global _IterativeRetrievalService
    if _IterativeRetrievalService is None:
        from app.services.iterative_retrieval import IterativeRetrievalService
        _IterativeRetrievalService = IterativeRetrievalService
    return _IterativeRetrievalService


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

--- LIVE SESSION TRANSCRIPT ---
{live_session}

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
        hybrid_retrieval: Any = None,
        iterative_retrieval: Any = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.record_repo = record_repo
        self.llm_factory = llm_factory
        self.db = db
        # RAG enhancement services (optional -- fall back to dense-only)
        self._hybrid = hybrid_retrieval
        self._iterative = iterative_retrieval

    # ── Public API ───────────────────────────────────────────────────────────

    def ask_question(
        self,
        patient_id: str,
        session_id: str,
        question: str,
        doctor_id: str = "",
        live_transcript: Optional[List[Dict[str, Any]]] = None,
        live_structured_record: Optional[Dict[str, Any]] = None,
    ) -> AssistantResponse:
        """
        Answer a clinical question about a patient using RAG.

        Steps:
        1. Embed the question.
        2. Retrieve relevant clinical facts (clinical_embeddings, is_final=True).
        3. Retrieve relevant transcript/document chunks (chunk_embeddings across
           all sessions for this patient).
        4. Fetch latest finalized MedicalRecord structured data.
        5. Incorporate live in-memory session transcript and structured record.
        6. Compute confidence from retrieval scores (or use floor if only live data).
        7. If no context at all: admit unavailability without calling LLM.
        8. Build grounded prompt and call LLM.
        9. Attach disclaimer if confidence < threshold.
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
        clinical_results = self._retrieve_clinical_facts(patient_id, query_vec, question)

        # 3. Chunk embeddings (all sessions for this patient)
        chunk_results = self._retrieve_chunks_for_patient(patient_id, query_vec, question)

        # 4. Structured records (latest 3 finalized from DB)
        structured_records = self._retrieve_structured_records(patient_id)

        # 5. Incorporate live in-memory session data
        has_live_data = bool(live_transcript or live_structured_record)
        if live_structured_record:
            # Prepend the live record so it takes priority over stale DB records
            structured_records = [live_structured_record] + structured_records

        # 6. Confidence — if live data is present but no pgvector hits yet,
        #    use a base confidence of 0.50 so the LLM can still be called.
        all_scores = [r["similarity"] for r in clinical_results + chunk_results]
        confidence = _compute_confidence(all_scores)
        if has_live_data and confidence == 0.0:
            confidence = 0.50  # live transcript is present but not yet embedded

        # 7. No context at all → admit unavailability
        if not all_scores and not structured_records and not has_live_data:
            return self._unavailable_response(
                "I don't have sufficient information in this patient's records "
                "to answer that question. Please consult the full chart."
            )

        # 8. Build prompt and call LLM
        prompt = _PROMPT_TEMPLATE.format(
            structured_records=_format_structured_records(structured_records),
            live_session=_format_live_transcript(live_transcript),
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

        # 9. Disclaimer if low confidence
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
        self, patient_id: str, query_vec: np.ndarray, question: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Retrieve clinical facts for a patient.

        Uses iterative retrieval -> hybrid retrieval -> dense-only, in
        order of preference based on what services are available.
        """
        # Path A: Iterative retrieval (multi-pass hybrid)
        if self._iterative and question:
            try:
                return self._iterative.retrieve_patient_facts(
                    patient_id=patient_id,
                    query=question,
                    top_k=TOP_K,
                    only_final=True,
                )
            except Exception as exc:
                logger.warning("Iterative fact retrieval failed, trying hybrid: %s", exc)

        # Path B: Single-pass hybrid retrieval
        if self._hybrid and question:
            try:
                return self._hybrid.search_patient_facts(
                    patient_id=patient_id,
                    query=question,
                    top_k=TOP_K,
                    only_final=True,
                )
            except Exception as exc:
                logger.warning("Hybrid fact retrieval failed, falling back to dense: %s", exc)

        # Path C: Dense-only (original behavior)
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
        self, patient_id: str, query_vec: np.ndarray, question: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Retrieve transcript/document chunks for a patient.

        Uses iterative retrieval -> hybrid retrieval -> dense-only, in
        order of preference based on what services are available.
        """
        # Path A: Iterative retrieval (multi-pass hybrid)
        if self._iterative and question:
            try:
                return self._iterative.retrieve_patient_chunks(
                    patient_id=patient_id,
                    query=question,
                    top_k=TOP_K,
                )
            except Exception as exc:
                logger.warning("Iterative chunk retrieval failed, trying hybrid: %s", exc)

        # Path B: Single-pass hybrid retrieval
        if self._hybrid and question:
            try:
                return self._hybrid.search_chunks_for_patient(
                    patient_id=patient_id,
                    query=question,
                    top_k=TOP_K,
                )
            except Exception as exc:
                logger.warning("Hybrid chunk retrieval failed, falling back to dense: %s", exc)

        # Path C: Dense-only (original behavior)
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


def _format_live_transcript(transcript: Optional[List[Dict[str, Any]]]) -> str:
    """Format the in-memory session utterances for the LLM prompt."""
    if not transcript:
        return "No live session transcript available."
    lines = []
    for entry in transcript:
        speaker = entry.get("speaker", "Unknown")
        text = entry.get("text", "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines) if lines else "No live session transcript available."


def _format_structured_records(records: List[Dict[str, Any]]) -> str:
    if not records:
        return "No finalized structured records available."
    parts = []
    # Metadata keys that should not be included as clinical content
    _META_KEYS = {"_conflicts", "_low_confidence", "_db_seeded_fields"}
    for i, rec in enumerate(records, start=1):
        parts.append(f"[Record {i}]")
        for key, value in rec.items():
            if key in _META_KEYS:
                continue
            # Skip empty / null leaf values
            if value is None:
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            # For dicts, skip if every nested value is None/empty
            if isinstance(value, dict) and all(
                v is None or v == "" or (isinstance(v, (list, dict)) and not v)
                for v in value.values()
            ):
                continue
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
