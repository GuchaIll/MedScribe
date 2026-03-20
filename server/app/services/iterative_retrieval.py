"""
Iterative Retrieval Service -- multi-pass retrieval for complex clinical queries.

When a single-pass retrieval returns insufficient or low-confidence results,
this service refines the query and performs additional retrieval passes:

  Pass 1: Original query -> hybrid search.
  Pass 2: If coverage is low, decompose the query into sub-questions
           and retrieve for each sub-question.
  Pass 3: (Optional) If a specific clinical entity is found but context
           is sparse, broaden the search with related terms.

The service deduplicates results across passes using chunk_id / fact id
and returns a unified, ranked result set.

Usage:
    from app.services.iterative_retrieval import IterativeRetrievalService
    svc = IterativeRetrievalService(hybrid_service, llm_factory)
    results = svc.retrieve(patient_id, session_id, question, top_k=8)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Thresholds
MIN_RESULTS_FOR_SKIP = 3       # If pass 1 returns >= this many, skip pass 2
HIGH_CONFIDENCE_FLOOR = 0.50   # If best RRF score >= this, skip refinement
MAX_SUB_QUESTIONS = 3          # Max sub-questions to decompose into
MAX_PASSES = 3                 # Hard cap on retrieval passes


class IterativeRetrievalService:
    """
    Multi-pass retrieval that refines queries when initial results are sparse.

    Works with HybridRetrievalService for the actual search, and optionally
    uses an LLM to decompose complex queries into sub-questions.
    """

    def __init__(
        self,
        hybrid_service: Any,  # HybridRetrievalService (avoid circular import)
        llm_factory: Optional[Callable] = None,
        min_results: int = MIN_RESULTS_FOR_SKIP,
        confidence_floor: float = HIGH_CONFIDENCE_FLOOR,
        max_sub_questions: int = MAX_SUB_QUESTIONS,
    ):
        self.hybrid = hybrid_service
        self.llm_factory = llm_factory
        self.min_results = min_results
        self.confidence_floor = confidence_floor
        self.max_sub_questions = max_sub_questions

    # ── Public API ───────────────────────────────────────────────────────────

    def retrieve_chunks(
        self,
        session_id: str,
        query: str,
        top_k: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Iterative chunk retrieval for a session.

        Pass 1: Hybrid search with original query.
        Pass 2: If insufficient, decompose into sub-questions and search each.
        Pass 3: If still sparse, broaden with clinical term expansion.

        Returns deduplicated, ranked results.
        """
        seen_ids: Set[str] = set()
        all_results: List[Dict[str, Any]] = []

        # Pass 1: Original query
        pass1 = self.hybrid.search_chunks(session_id, query, top_k=top_k)
        all_results, seen_ids = self._merge_results(
            all_results, pass1, seen_ids, id_key="chunk_id"
        )

        if self._sufficient(all_results):
            logger.debug("Pass 1 sufficient (%d results), skipping refinement", len(all_results))
            return all_results[:top_k]

        # Pass 2: Sub-question decomposition
        sub_questions = self._decompose_query(query)
        for sq in sub_questions:
            pass2 = self.hybrid.search_chunks(session_id, sq, top_k=top_k // 2)
            all_results, seen_ids = self._merge_results(
                all_results, pass2, seen_ids, id_key="chunk_id"
            )

        if self._sufficient(all_results):
            logger.debug("Pass 2 sufficient (%d results), skipping broadening", len(all_results))
            return self._rank_and_trim(all_results, top_k)

        # Pass 3: Clinical term expansion
        expanded_terms = self._expand_clinical_terms(query)
        for term in expanded_terms:
            pass3 = self.hybrid.search_chunks(session_id, term, top_k=top_k // 2)
            all_results, seen_ids = self._merge_results(
                all_results, pass3, seen_ids, id_key="chunk_id"
            )

        return self._rank_and_trim(all_results, top_k)

    def retrieve_patient_chunks(
        self,
        patient_id: str,
        query: str,
        top_k: int = 8,
    ) -> List[Dict[str, Any]]:
        """Iterative chunk retrieval across all sessions for a patient."""
        seen_ids: Set[str] = set()
        all_results: List[Dict[str, Any]] = []

        # Pass 1
        pass1 = self.hybrid.search_chunks_for_patient(patient_id, query, top_k=top_k)
        all_results, seen_ids = self._merge_results(
            all_results, pass1, seen_ids, id_key="chunk_id"
        )

        if self._sufficient(all_results):
            return all_results[:top_k]

        # Pass 2
        sub_questions = self._decompose_query(query)
        for sq in sub_questions:
            pass2 = self.hybrid.search_chunks_for_patient(patient_id, sq, top_k=top_k // 2)
            all_results, seen_ids = self._merge_results(
                all_results, pass2, seen_ids, id_key="chunk_id"
            )

        return self._rank_and_trim(all_results, top_k)

    def retrieve_patient_facts(
        self,
        patient_id: str,
        query: str,
        top_k: int = 10,
        fact_type: Optional[str] = None,
        only_final: bool = True,
    ) -> List[Dict[str, Any]]:
        """Iterative clinical fact retrieval for a patient."""
        seen_ids: Set[str] = set()
        all_results: List[Dict[str, Any]] = []

        # Pass 1
        pass1 = self.hybrid.search_patient_facts(
            patient_id, query, top_k=top_k,
            fact_type=fact_type, only_final=only_final,
        )
        all_results, seen_ids = self._merge_results(
            all_results, pass1, seen_ids, id_key="id"
        )

        if self._sufficient(all_results):
            return all_results[:top_k]

        # Pass 2
        sub_questions = self._decompose_query(query)
        for sq in sub_questions:
            pass2 = self.hybrid.search_patient_facts(
                patient_id, sq, top_k=top_k // 2,
                fact_type=fact_type, only_final=only_final,
            )
            all_results, seen_ids = self._merge_results(
                all_results, pass2, seen_ids, id_key="id"
            )

        # Pass 3: expand clinical terms for fact retrieval
        expanded_terms = self._expand_clinical_terms(query)
        for term in expanded_terms:
            pass3 = self.hybrid.search_patient_facts(
                patient_id, term, top_k=top_k // 2,
                fact_type=fact_type, only_final=only_final,
            )
            all_results, seen_ids = self._merge_results(
                all_results, pass3, seen_ids, id_key="id"
            )

        return self._rank_and_trim(all_results, top_k)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _sufficient(self, results: List[Dict[str, Any]]) -> bool:
        """Check if current results are sufficient to skip further passes."""
        if len(results) >= self.min_results:
            return True
        if results:
            best_score = max(r.get("rrf_score", 0.0) for r in results)
            if best_score >= self.confidence_floor:
                return True
        return False

    def _merge_results(
        self,
        existing: List[Dict[str, Any]],
        new: List[Dict[str, Any]],
        seen_ids: Set[str],
        id_key: str = "chunk_id",
    ) -> tuple:
        """Merge new results into existing, deduplicating by id_key."""
        for item in new:
            item_id = str(item.get(id_key, ""))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                existing.append(item)
        return existing, seen_ids

    def _rank_and_trim(
        self, results: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        """Sort results by RRF score (or similarity) and trim to top_k."""
        results.sort(
            key=lambda r: r.get("rrf_score", r.get("similarity", 0.0)),
            reverse=True,
        )
        return results[:top_k]

    def _decompose_query(self, query: str) -> List[str]:
        """
        Decompose a complex query into sub-questions.

        Uses LLM if available, otherwise falls back to heuristic decomposition.
        """
        if self.llm_factory:
            return self._llm_decompose(query)
        return self._heuristic_decompose(query)

    def _llm_decompose(self, query: str) -> List[str]:
        """Use LLM to decompose the query into simpler sub-questions."""
        try:
            llm = self.llm_factory()
            prompt = (
                "You are a medical information retrieval assistant. "
                "Break the following clinical question into 1-3 simpler, "
                "more specific sub-questions that would each help retrieve "
                "relevant medical records. Return ONLY the sub-questions, "
                "one per line, with no numbering or bullets.\n\n"
                f"Question: {query}\n\n"
                "Sub-questions:"
            )
            response = llm.generate_response(prompt)
            lines = [
                line.strip()
                for line in response.strip().split("\n")
                if line.strip() and len(line.strip()) > 5
            ]
            return lines[: self.max_sub_questions]
        except Exception as e:
            logger.warning("LLM decomposition failed: %s", e)
            return self._heuristic_decompose(query)

    def _heuristic_decompose(self, query: str) -> List[str]:
        """
        Rule-based query decomposition for when LLM is not available.

        Strategies:
          1. Split "and" conjunctions: "allergies and medications" -> 2 queries
          2. Extract clinical entities and search them individually
        """
        sub_questions: List[str] = []

        # Strategy 1: Split on "and" / "&" if the query has conjunctions
        if re.search(r"\band\b|&", query, re.IGNORECASE):
            parts = re.split(r"\band\b|&", query, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                if len(part) > 5:
                    sub_questions.append(part)

        # Strategy 2: Extract quoted terms or clinical entity patterns
        quoted = re.findall(r'"([^"]+)"', query)
        for q in quoted:
            if q not in sub_questions:
                sub_questions.append(q)

        # Limit
        return sub_questions[: self.max_sub_questions]

    def _expand_clinical_terms(self, query: str) -> List[str]:
        """
        Expand query with related clinical terms using heuristic mappings.

        This is a lightweight term expansion that does not require an LLM.
        It maps common clinical abbreviations and synonyms.
        """
        expansions: List[str] = []

        # Common clinical abbreviation/synonym mappings
        _TERM_MAP = {
            "bp": "blood pressure",
            "hr": "heart rate pulse",
            "rr": "respiratory rate breathing",
            "temp": "temperature fever",
            "o2": "oxygen saturation spo2",
            "spo2": "oxygen saturation o2 sat",
            "hba1c": "hemoglobin a1c glycated",
            "a1c": "hba1c hemoglobin glycated",
            "bmi": "body mass index weight height",
            "cbc": "complete blood count hemoglobin wbc platelets",
            "bmp": "basic metabolic panel sodium potassium glucose creatinine",
            "cmp": "comprehensive metabolic panel liver kidney electrolytes",
            "ua": "urinalysis urine",
            "ekg": "electrocardiogram ecg heart rhythm",
            "ecg": "electrocardiogram ekg heart rhythm",
            "ct": "computed tomography scan imaging",
            "mri": "magnetic resonance imaging scan",
            "copd": "chronic obstructive pulmonary disease",
            "chf": "congestive heart failure",
            "dm": "diabetes mellitus",
            "htn": "hypertension high blood pressure",
            "cad": "coronary artery disease",
            "ckd": "chronic kidney disease renal",
            "gi": "gastrointestinal",
            "uti": "urinary tract infection",
            "dvt": "deep vein thrombosis",
            "pe": "pulmonary embolism",
            "mi": "myocardial infarction heart attack",
            "cva": "cerebrovascular accident stroke",
            "tia": "transient ischemic attack mini stroke",
            "nsaid": "nonsteroidal anti inflammatory ibuprofen naproxen",
            "ace": "angiotensin converting enzyme inhibitor",
            "arb": "angiotensin receptor blocker",
            "ssri": "selective serotonin reuptake inhibitor antidepressant",
            "ppi": "proton pump inhibitor omeprazole",
            "rx": "prescription medication",
            "dx": "diagnosis",
            "tx": "treatment therapy",
            "hx": "history",
            "sx": "symptoms",
            "fx": "fracture",
            "pmh": "past medical history",
            "fh": "family history",
            "sh": "social history",
            "ros": "review of systems",
        }

        query_lower = query.lower()
        tokens = re.findall(r"[a-zA-Z0-9]+", query_lower)

        for token in tokens:
            if token in _TERM_MAP and _TERM_MAP[token] not in expansions:
                expansions.append(_TERM_MAP[token])

        # Limit to avoid too many queries
        return expansions[:2]
