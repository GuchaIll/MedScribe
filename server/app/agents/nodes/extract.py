"""
Agent B -- Candidate Extractor (Bedrock-style Query-Value Extraction)

Purpose: Extract typed candidate facts with confidence scores and evidence spans.
Uses targeted sub-queries (query-value pairs) instead of a monolithic prompt.
Each query targets a specific entity category, reducing prompt size and improving
extraction accuracy.

DB integration:
  - Reads patient_record_fields (prior history) to augment the LLM prompt
  - Uses EmbeddingService (Layer 1) to verify grounding of extracted facts
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional
from uuid import uuid4

from ..config import AgentContext
from ..state import GraphState

logger = logging.getLogger(__name__)


# Medical entity canonicalization mappings
MEDICATION_ALIASES = {
    "amoxicillin": ["amoxicillin", "amoxil", "moxatag"],
    "lisinopril": ["lisinopril", "prinivil", "zestril"],
    "metformin": ["metformin", "glucophage", "fortamet"],
    "atorvastatin": ["atorvastatin", "lipitor"],
    "levothyroxine": ["levothyroxine", "synthroid", "levoxyl"],
    "amlodipine": ["amlodipine", "norvasc"],
    "metoprolol": ["metoprolol", "lopressor", "toprol"],
    "omeprazole": ["omeprazole", "prilosec"],
}

ALLERGY_ALIASES = {
    "penicillin": ["penicillin", "pcn", "pen"],
    "sulfa": ["sulfa", "sulfamethoxazole", "sulfonamide"],
    "aspirin": ["aspirin", "asa"],
    "codeine": ["codeine"],
    "morphine": ["morphine"],
}


# ---------------------------------------------------------------------------
# Query-Value extraction categories (Bedrock-style)
# Each category is a targeted sub-query with its own compact prompt.
# ---------------------------------------------------------------------------

_EXTRACTION_QUERIES: List[Dict[str, Any]] = [
    {
        "category": "demographics",
        "fact_types": ["patient_name", "patient_dob", "patient_sex", "patient_mrn"],
        "prompt": (
            "Extract patient demographics. Return JSON: "
            '{"facts":[{"fact_type":"patient_name"|"patient_dob"|"patient_sex"|"patient_mrn",'
            '"value":"...","confidence":0.0-1.0,"evidence_text":"exact quote 15-50 words"}]}'
        ),
        "max_tokens": 300,
    },
    {
        "category": "chief_complaint_hpi",
        "fact_types": ["chief_complaint", "hpi_event"],
        "prompt": (
            "Extract chief complaint and HPI events. Return JSON: "
            '{"facts":[{"fact_type":"chief_complaint","value":{"free_text":"...","onset":"...","severity":"...","location":"..."},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"hpi_event","value":{"symptom":"...","onset":"...","progression":"...","triggers":"...","relieving_factors":"..."},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 500,
    },
    {
        "category": "medications_allergies",
        "fact_types": ["medication", "allergy"],
        "prompt": (
            "Extract ALL medications and allergies. Return JSON: "
            '{"facts":[{"fact_type":"medication","value":{"name":"...","dose":"...","route":"...","frequency":"...","indication":"..."},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"allergy","value":{"substance":"...","reaction":"...","severity":"mild|moderate|anaphylaxis","category":"drug|food|environmental"},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 500,
    },
    {
        "category": "vitals_labs",
        "fact_types": ["vital", "lab_result"],
        "prompt": (
            "Extract vitals and lab results. Return JSON: "
            '{"facts":[{"fact_type":"vital","value":{"type":"blood_pressure|heart_rate|respiratory_rate|temperature|spo2|height|weight|bmi",'
            '"value":"...","unit":"..."},"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"lab_result","value":{"test":"...","value":"...","unit":"...","reference_range":"...","abnormal":true|false},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 500,
    },
    {
        "category": "conditions_diagnoses",
        "fact_types": ["chronic_condition", "diagnosis", "problem", "risk_factor"],
        "prompt": (
            "Extract conditions, diagnoses, problems, and risk factors. Return JSON: "
            '{"facts":[{"fact_type":"chronic_condition","value":{"name":"...","icd10_code":"...","status":"active|resolved"},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"diagnosis","value":{"code":"...","description":"..."},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"problem","value":{"name":"...","status":"active|chronic|resolved"},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 500,
    },
    {
        "category": "history_social_ros",
        "fact_types": [
            "family_history", "social_history", "ros_finding",
            "hospitalization", "surgery", "physical_exam_finding",
        ],
        "prompt": (
            "Extract family history, social history, review of systems, past hospitalizations, "
            "surgeries, and physical exam findings. Return JSON: "
            '{"facts":[{"fact_type":"family_history|social_history|ros_finding|hospitalization|surgery|physical_exam_finding",'
            '"value":{...},"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 600,
    },
    {
        "category": "assessment_plan",
        "fact_types": ["assessment", "plan"],
        "prompt": (
            "Extract clinical assessment and plan. Return JSON: "
            '{"facts":[{"fact_type":"assessment","value":{"likely_diagnoses":[...],"differential_diagnoses":[...],"clinical_reasoning":"..."},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"},'
            '{"fact_type":"plan","value":{"medications_prescribed":[...],"tests_ordered":[...],"lifestyle_recommendations":[...],"follow_up":"...","referrals":[...]},'
            '"confidence":0.0-1.0,"evidence_text":"exact quote"}]}'
        ),
        "max_tokens": 600,
    },
]


def extract_candidates_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Extract candidate clinical facts using Bedrock-style query-value pairs.

    Instead of one massive prompt, dispatches targeted sub-queries in parallel
    (one per entity category). Each sub-query returns only the specific entity
    types it targets. Results are merged, deduplicated, canonicalized, and
    grounded.
    """
    state = state.copy() if isinstance(state, dict) else state

    chunks = state.get("chunks", [])
    if not chunks:
        chunks = _create_chunks_from_conversation_log(state)

    candidates: List[Dict[str, Any]] = []
    controls = state.get("controls", {"attempts": {}, "budget": {}})

    node_name = "extract_candidates"
    attempts = controls.get("attempts", {})
    attempts[node_name] = attempts.get(node_name, 0) + 1

    budget = controls.get("budget", {})
    max_llm_calls = budget.get("max_total_llm_calls", ctx.max_llm_calls if ctx else 30)
    llm_calls_used = budget.get("llm_calls_used", 0)

    if llm_calls_used >= max_llm_calls:
        logger.info("[Extract Candidates] Budget exhausted: %d/%d LLM calls", llm_calls_used, max_llm_calls)
        state["candidate_facts"] = candidates
        return state

    # Build patient history context from DB (if loaded)
    patient_history_prompt = _build_patient_history_prompt(state)

    # Combine all chunk text into a single context block
    full_text = "\n\n---\n\n".join([
        f"[Chunk {i}] ({chunk.get('source', 'unknown')})\n{chunk.get('text', '')}"
        for i, chunk in enumerate(chunks)
    ])

    # Get the shared LLM client from context
    llm = ctx.llm if ctx and ctx.llm else None
    if llm is None and ctx and ctx.llm_factory:
        llm = ctx.llm_factory()

    if llm is None:
        logger.warning("[Extract Candidates] No LLM client available")
        state["candidate_facts"] = candidates
        return state

    # Dispatch all category queries in parallel using ThreadPoolExecutor.
    # Limit to 3 concurrent workers to avoid saturating the LLM endpoint
    # (Groq's free tier serialises requests under the hood for large models).
    _MAX_EXTRACT_WORKERS = 3
    _PER_CALL_TIMEOUT_S = 30

    def _run_query(query: Dict[str, Any]) -> List[Dict[str, Any]]:
        return _call_category_extraction(
            llm, query, full_text, patient_history_prompt, chunks
        )

    import time as _time
    _t0 = _time.monotonic()

    with ThreadPoolExecutor(max_workers=_MAX_EXTRACT_WORKERS) as pool:
        futures = {
            pool.submit(_run_query, q): q["category"]
            for q in _EXTRACTION_QUERIES
        }
        for future in as_completed(futures):
            category = futures[future]
            try:
                result = future.result(timeout=_PER_CALL_TIMEOUT_S)
                candidates.extend(result)
                print(f"[Extract] Category {category} returned {len(result)} facts")
            except TimeoutError:
                logger.warning("[Extract] Category %s timed out after %ds", category, _PER_CALL_TIMEOUT_S)
            except Exception as exc:
                logger.warning("[Extract Candidates] Category %s failed: %s", category, exc)

    _t1 = _time.monotonic()
    print(f"[Extract] LLM parallel queries took {_t1 - _t0:.1f}s for {len(_EXTRACTION_QUERIES)} categories")

    # All category queries count as LLM calls
    llm_calls_used += len(_EXTRACTION_QUERIES)

    # Canonicalize entities
    candidates = _canonicalize_candidates(candidates)

    # Ensure all candidates have evidence spans
    candidates = _ensure_evidence_spans(candidates, chunks)

    # Deduplicate across categories (same fact_type + similar value)
    candidates = _deduplicate_candidates(candidates)

    # Layer 1: Grounding verification via embeddings (if available)
    if ctx and ctx.embedding_service is not None:
        _t2 = _time.monotonic()
        candidates = _apply_grounding_verification(candidates, ctx)
        _t3 = _time.monotonic()
        print(f"[Extract] Grounding verification took {_t3 - _t2:.1f}s for {len(candidates)} candidates")

    # Update state
    state["candidate_facts"] = candidates
    controls["attempts"] = attempts
    budget["llm_calls_used"] = llm_calls_used
    controls["budget"] = budget
    state["controls"] = controls

    logger.info(
        "[Extract Candidates] Extracted %d candidate facts via %d parallel queries "
        "(LLM calls: %d/%d)",
        len(candidates), len(_EXTRACTION_QUERIES), llm_calls_used, max_llm_calls,
    )

    return state


# ---------------------------------------------------------------------------
# Per-category LLM call
# ---------------------------------------------------------------------------

def _call_category_extraction(
    llm: Any,
    query: Dict[str, Any],
    text: str,
    patient_history_prompt: str,
    chunks: List[Dict],
) -> List[Dict[str, Any]]:
    """Run a single category extraction query against the LLM."""

    system = (
        "You are a medical entity extraction system. "
        "Extract ONLY the requested entity types from the clinical text. "
        "Return ONLY valid JSON. No explanations, no markdown."
    )

    prompt = f"{system}\n\n{query['prompt']}"

    if patient_history_prompt:
        prompt += f"\n\n{patient_history_prompt}"

    prompt += f"\n\nText to analyze:\n{text}\n\nJSON output:"

    max_retries = 1
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                prompt_with_retry = prompt + "\n\nIMPORTANT: Previous attempt failed. Return ONLY valid JSON.\n"
            else:
                prompt_with_retry = prompt

            response = llm.generate_response(
                prompt_with_retry, max_tokens=query["max_tokens"]
            ).strip()

            # Strip markdown fences
            if response.startswith("```"):
                response = re.sub(r'^```(?:json)?\s*\n?', '', response)
                response = re.sub(r'\n?```\s*$', '', response)

            data = json.loads(response)

            results = []
            for fact in data.get("facts", []):
                fact_id = str(uuid4())[:8]
                evidence_text = fact.get("evidence_text", "")

                evidence_span = {
                    "source": chunks[0].get("source", "transcript") if chunks else "transcript",
                    "source_id": chunks[0].get("source_id", "unknown") if chunks else "unknown",
                    "locator": {},
                    "snippet": evidence_text[:200],
                    "strength": fact.get("confidence", 0.5),
                }

                results.append({
                    "fact_id": fact_id,
                    "type": fact.get("fact_type", "unknown"),
                    "value": fact.get("value", {}),
                    "confidence": fact.get("confidence", 0.5),
                    "provenance": {"evidence": [evidence_span]},
                    "normalized": False,
                    "conflict_group": None,
                })
            return results

        except json.JSONDecodeError:
            if attempt == max_retries:
                logger.warning(
                    "[Extract] Category %s JSON parse failed after %d attempts",
                    query["category"], max_retries + 1,
                )
                return []
        except Exception as exc:
            logger.warning("[Extract] Category %s error: %s", query["category"], exc)
            return []

    return []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate facts across categories (keep highest confidence)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        key = _candidate_dedup_key(c)
        if key in seen:
            if c.get("confidence", 0) > seen[key].get("confidence", 0):
                seen[key] = c
        else:
            seen[key] = c
    return list(seen.values())


def _candidate_dedup_key(c: Dict[str, Any]) -> str:
    """Build a deduplication key from fact type and core value."""
    ft = c.get("type", "")
    val = c.get("value", {})
    if isinstance(val, dict):
        # Use the first meaningful field as key
        for k in ("name", "substance", "test", "free_text", "description", "symptom", "type"):
            if k in val:
                return f"{ft}:{str(val[k]).lower().strip()}"
        return f"{ft}:{json.dumps(val, sort_keys=True)}"
    return f"{ft}:{str(val).lower().strip()}"


def _create_chunks_from_conversation_log(state: GraphState) -> List[Dict[str, Any]]:
    """Fallback: create chunks from conversation log if chunks not yet generated."""
    chunks = []
    conversation_log = state.get("conversation_log", [])
    
    for log_entry in conversation_log:
        for seg in log_entry.get("segments", []):
            chunk = {
                "chunk_id": str(uuid4())[:8],
                "source": "transcript",
                "source_id": state.get("session_id", "unknown"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": seg.get("cleaned_text") or seg.get("raw_text", ""),
                "metadata": {"speaker": seg.get("speaker", "unknown")}
            }
            chunks.append(chunk)
    
    return chunks


def _canonicalize_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canonicalize drug names and allergens to standard forms."""
    
    for candidate in candidates:
        fact_type = candidate.get("type", "")
        value = candidate.get("value", {})
        
        if fact_type == "medication" and "name" in value:
            med_name = value["name"].lower()
            # Check if this is an alias
            for canonical, aliases in MEDICATION_ALIASES.items():
                if med_name in aliases:
                    value["name"] = canonical.capitalize()
                    value["original_name"] = med_name
                    candidate["normalized"] = True
                    break
        
        elif fact_type == "allergy" and "substance" in value:
            allergy_name = value["substance"].lower()
            for canonical, aliases in ALLERGY_ALIASES.items():
                if allergy_name in aliases:
                    value["substance"] = canonical.capitalize()
                    value["original_substance"] = allergy_name
                    candidate["normalized"] = True
                    break
    
    return candidates


def _ensure_evidence_spans(candidates: List[Dict[str, Any]], chunks: List[Dict]) -> List[Dict[str, Any]]:
    """Ensure all candidates have at least one evidence span with proper locators."""
    
    for candidate in candidates:
        provenance = candidate.get("provenance", {})
        evidence_list = provenance.get("evidence", []) if isinstance(provenance, dict) else []
        
        if not evidence_list:
            # Create minimal evidence span
            evidence_list = [{
                "source": "transcript",
                "source_id": "unknown",
                "locator": {},
                "snippet": f"Extracted {candidate.get('type', 'fact')}",
                "strength": candidate.get("confidence", 0.5)
            }]
            candidate["provenance"] = {"evidence": evidence_list}
        
        # Enhance evidence with better locators if possible
        for evidence in evidence_list:
            if not evidence.get("locator"):
                snippet = evidence.get("snippet", "")
                # Try to find matching chunk
                for chunk in chunks:
                    if snippet[:50] in chunk.get("text", ""):
                        if chunk.get("source") == "transcript":
                            evidence["locator"] = {
                                "start_time": chunk.get("start_time"),
                                "end_time": chunk.get("end_time")
                            }
                        else:
                            evidence["locator"] = {
                                "start_char": chunk.get("start_char"),
                                "end_char": chunk.get("end_char")
                            }
                        break
    
    return candidates


# ─── Patient history prompt builder ─────────────────────────────────────────

def _build_patient_history_prompt(state: GraphState) -> str:
    """
    Build a context section for the LLM prompt from patient_record_fields.

    If load_patient_context has populated the state with prior facts,
    we inject them so the LLM can:
      - Cross-reference existing allergies / medications
      - Flag new vs. previously-known findings
      - Increase confidence for corroborated facts
    """
    prf = state.get("patient_record_fields")
    if not prf or not prf.get("loaded_from_db"):
        return ""

    sections = []
    sections.append("PATIENT HISTORY (from database — use for cross-referencing, NOT as new evidence):")

    # Demographics
    demo = prf.get("demographics", {})
    if demo:
        sections.append(f"  Patient: {demo.get('full_name', 'Unknown')}, "
                        f"DOB: {demo.get('dob', 'N/A')}, "
                        f"Sex: {demo.get('sex', 'N/A')}")

    # Prior facts
    prior_facts = prf.get("prior_facts", {})
    if prior_facts:
        for fact_type, facts in prior_facts.items():
            keys = [f.get("fact_key", "?") for f in facts[:5]]
            sections.append(f"  Known {fact_type}s: {', '.join(keys)}")

    sections.append(
        "INSTRUCTIONS: If you extract a fact that matches a known item above, "
        "boost its confidence. If it contradicts, flag it and keep both."
    )

    return "\n".join(sections)


# ─── Layer 1: Grounding verification ────────────────────────────────────────

def _apply_grounding_verification(
    candidates: List[Dict[str, Any]],
    ctx: AgentContext,
) -> List[Dict[str, Any]]:
    """
    Layer 1 — Extraction-time span verification.

    For each candidate that has an evidence snippet, compute cosine
    similarity between the snippet and the fact text. If below the
    grounding threshold, downgrade confidence.
    """
    if ctx.embedding_service is None:
        return candidates

    for candidate in candidates:
        provenance = candidate.get("provenance", {})
        evidence_list = provenance.get("evidence", []) if isinstance(provenance, dict) else []
        if not evidence_list:
            continue

        snippet = evidence_list[0].get("snippet", "")
        if not snippet or len(snippet) < 10:
            continue

        try:
            fact_text = ctx.embedding_service._fact_to_text(candidate)
            grounding_score, is_grounded = ctx.embedding_service.verify_grounding(
                source_span=snippet,
                extracted_text=fact_text,
            )

            candidate["grounding_score"] = grounding_score

            if not is_grounded:
                # Downgrade confidence for ungrounded facts
                original_conf = candidate.get("confidence", 0.5)
                candidate["confidence"] = min(original_conf, 0.4)
                candidate["grounding_warning"] = (
                    f"Low grounding score ({grounding_score:.3f}) — "
                    "fact may not be well-supported by source text"
                )
                logger.warning(
                    f"[Extract] Fact {candidate.get('fact_id')} failed grounding: "
                    f"{grounding_score:.3f} < {ctx.grounding_threshold}"
                )
        except Exception as e:
            logger.debug(f"[Extract] Grounding check failed for {candidate.get('fact_id')}: {e}")

    return candidates
