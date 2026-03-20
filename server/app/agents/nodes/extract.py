"""
Agent B — Candidate Extractor (Initial Extraction)

Purpose: Extract typed candidate facts with confidence scores and evidence spans.
Deterministic work: canonicalize entities, assign strict fact_type schema.
Output quality: All candidates must include at least one evidence span.

DB integration:
  - Reads patient_record_fields (prior history) to augment the LLM prompt
  - Uses EmbeddingService (Layer 1) to verify grounding of extracted facts
"""

import json
import logging
import re
from typing import Dict, List, Any, Optional
from uuid import uuid4

from ..config import AgentContext
from ..state import GraphState
from ...models.llm import LLMClient

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


def extract_candidates_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Extract candidate clinical facts from chunks using LLM with structured output.
    
    Agent B: Candidate Extractor
    - Extracts: patient demographics, allergies, medications, diagnoses, vitals, labs
    - Assigns confidence scores (0.0-1.0)
    - Creates evidence spans with provenance
    - Canonicalizes drug names and allergens
    - Injects patient history from DB into LLM prompt (if available)
    - Applies Layer 1 grounding verification via embeddings (if available)
    - Retries on invalid JSON (bounded by budget)
    """
    state = state.copy() if isinstance(state, dict) else state
    
    chunks = state.get("chunks", [])
    if not chunks:
        # Fallback: extract from conversation_log if chunks not available yet
        chunks = _create_chunks_from_conversation_log(state)
    
    candidates: List[Dict[str, Any]] = []
    controls = state.get("controls", {"attempts": {}, "budget": {}})
    
    # Track extraction attempts
    node_name = "extract_candidates"
    attempts = controls.get("attempts", {})
    attempts[node_name] = attempts.get(node_name, 0) + 1
    
    # Budget tracking
    budget = controls.get("budget", {})
    max_llm_calls = budget.get("max_total_llm_calls", ctx.max_llm_calls if ctx else 30)
    llm_calls_used = budget.get("llm_calls_used", 0)
    
    if llm_calls_used >= max_llm_calls:
        print(f"[Extract Candidates] Budget exhausted: {llm_calls_used}/{max_llm_calls} LLM calls")
        state["candidate_facts"] = candidates
        return state
    
    # Build patient history context from DB (if loaded)
    patient_history_prompt = _build_patient_history_prompt(state)
    
    # Process chunks in batches for efficiency
    batch_size = 3
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        batch_text = "\n\n---\n\n".join([
            f"[Chunk {j}] ({chunk.get('source', 'unknown')})\n{chunk.get('text', '')}"
            for j, chunk in enumerate(batch, start=i)
        ])
        
        # Extract candidates with retry logic
        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                llm_calls_used += 1
                extracted = _call_extraction_llm(batch_text, batch, retry, patient_history_prompt)
                
                if extracted:
                    candidates.extend(extracted)
                    break  # Success
                    
            except json.JSONDecodeError as e:
                print(f"[Extract Candidates] JSON decode error (attempt {retry+1}): {e}")
                if retry == max_retries:
                    # Failed after retries - create low-confidence fallback
                    candidates.extend(_create_fallback_candidates(batch))
            except Exception as e:
                print(f"[Extract Candidates] Error: {e}")
                if retry == max_retries:
                    candidates.extend(_create_fallback_candidates(batch))
        
        if llm_calls_used >= max_llm_calls:
            print(f"[Extract Candidates] Budget limit reached during processing")
            break
    
    # Canonicalize entities
    candidates = _canonicalize_candidates(candidates)
    
    # Ensure all candidates have evidence spans
    candidates = _ensure_evidence_spans(candidates, chunks)
    
    # Layer 1: Grounding verification via embeddings (if available)
    if ctx and ctx.embedding_service is not None:
        candidates = _apply_grounding_verification(candidates, ctx)
    
    # Update state
    state["candidate_facts"] = candidates
    controls["attempts"] = attempts
    budget["llm_calls_used"] = llm_calls_used
    controls["budget"] = budget
    state["controls"] = controls
    
    print(f"[Extract Candidates] Extracted {len(candidates)} candidate facts "
          f"(LLM calls: {llm_calls_used}/{max_llm_calls})")
    
    return state


def _call_extraction_llm(text: str, chunks: List[Dict], retry_count: int, patient_history_prompt: str = "") -> List[Dict[str, Any]]:
    """Call LLM to extract structured medical entities."""
    
    prompt = """You are a medical entity extraction system. Extract clinical facts from the text.

CRITICAL: Return ONLY valid JSON. No explanations, no markdown, just JSON.

Extract ALL of these entity types (omit types not present, but be thorough):

DEMOGRAPHICS (scalar — one value per patient):
- patient_name:       value: "Full Name"
- patient_dob:        value: "YYYY-MM-DD"
- patient_sex:        value: "Male" | "Female" | "Other"
- patient_mrn:        value: "MRN string"

CHIEF COMPLAINT (mandatory for every visit):
- chief_complaint:    value: {free_text, onset, duration, severity (e.g. "7/10"), location}

HISTORY OF PRESENT ILLNESS (one entry per symptom/event):
- hpi_event:          value: {symptom, onset, progression, triggers, relieving_factors,
                               associated_symptoms, timeline, timestamp}

PAST MEDICAL HISTORY:
- chronic_condition:  value: {name, icd10_code, onset_year, status}
  Examples: hypertension, diabetes type 2, obesity, hyperlipidemia, COPD
- hospitalization:    value: {reason, date, facility, duration}
- surgery:            value: {name, date, facility}

MEDICATIONS (list every drug mentioned):
- medication:         value: {name, dose, route, frequency, indication, start_date}
  Examples: "Metformin 500mg BID PO", "Lisinopril 10mg daily"

ALLERGIES (safety-critical — extract ALL):
- allergy:            value: {substance, reaction, severity ("mild"|"moderate"|"anaphylaxis"),
                               category ("drug"|"food"|"environmental")}

FAMILY HISTORY:
- family_history:     value: {member ("mother"|"father"|"sibling"|"child"|"grandparent"),
                               conditions: [...], alive: true|false,
                               age_at_death, cause_of_death}

SOCIAL HISTORY:
- social_history:     value: {tobacco, alcohol, drug_use, occupation, exercise, diet}
  OR: {category: "tobacco", value: "20 pack-years, quit 2010"}

REVIEW OF SYSTEMS (one entry, dict keyed by system):
- ros_finding:        value: {system ("cardiovascular"|"respiratory"|"neurological"|
                                       "gastrointestinal"|"musculoskeletal"|"dermatological"|
                                       "psychiatric"|"endocrine"|"genitourinary"|"hematologic"),
                               finding: "chest pain, palpitations"}

VITALS (one entry per measurement):
- vital:              value: {type ("blood_pressure"|"heart_rate"|"respiratory_rate"|
                                     "temperature"|"spo2"|"height"|"weight"|"bmi"),
                               value: "120/80", unit: "mmHg"}

LABS (one entry per test with ALL details):
- lab_result:         value: {test, value, unit, reference_range, date, abnormal: true|false}
  Include: cholesterol, LDL, HDL, triglycerides, glucose, HbA1c, creatinine, BUN,
           sodium, potassium, AST, ALT, ALP, CBC components, TSH, vitamin D, B12

PHYSICAL EXAM:
- physical_exam_finding: value: {system ("general"|"cardiovascular"|"respiratory"|
                                          "neurological"|"abdomen"|"musculoskeletal"|
                                          "skin"|"head_neck"),
                                   finding: "Regular rhythm, no murmurs"}

DIAGNOSES (ICD-10 coded when possible):
- diagnosis:          value: {code, description}

PROBLEM LIST (active issues):
- problem:            value: {name, status ("active"|"chronic"|"resolved")}

RISK FACTORS:
- risk_factor:        value: {name, severity ("low"|"moderate"|"high"), source}

ASSESSMENT & PLAN:
- assessment:         value: {likely_diagnoses: [...], differential_diagnoses: [...],
                               clinical_reasoning}
- plan:               value: {medications_prescribed: [...], tests_ordered: [...],
                               lifestyle_recommendations: [...], follow_up, referrals: [...]}

For EACH entity provide:
1. fact_type: one of the types above
2. value: dict as specified
3. confidence: 0.0-1.0 (clarity of source text)
4. evidence_text: exact quote from source (15-50 words)

"""
    
    # Inject patient history context if available
    if patient_history_prompt:
        prompt += patient_history_prompt + "\n"
    
    prompt += """Output format:
{
  "facts": [
    {
      "fact_type": "patient_name",
      "value": "Jane Smith",
      "confidence": 0.97,
      "evidence_text": "Patient: Jane Smith, DOB 1975-04-12"
    },
    {
      "fact_type": "chief_complaint",
      "value": {"free_text": "chest pain for 2 weeks", "onset": "2 weeks ago", "severity": "6/10", "location": "substernal"},
      "confidence": 0.92,
      "evidence_text": "Patient reports substernal chest pain for the past 2 weeks, rated 6 out of 10"
    },
    {
      "fact_type": "chronic_condition",
      "value": {"name": "hypertension", "icd10_code": "I10", "status": "active"},
      "confidence": 0.93,
      "evidence_text": "known hypertension managed with Lisinopril"
    },
    {
      "fact_type": "medication",
      "value": {"name": "Lisinopril", "dose": "10mg", "frequency": "daily", "route": "oral"},
      "confidence": 0.95,
      "evidence_text": "patient taking Lisinopril 10mg once daily"
    },
    {
      "fact_type": "allergy",
      "value": {"substance": "Penicillin", "reaction": "rash", "severity": "moderate", "category": "drug"},
      "confidence": 0.90,
      "evidence_text": "allergic to penicillin, develops rash"
    },
    {
      "fact_type": "vital",
      "value": {"type": "blood_pressure", "value": "142/88", "unit": "mmHg"},
      "confidence": 0.98,
      "evidence_text": "BP 142/88 mmHg at today's visit"
    },
    {
      "fact_type": "lab_result",
      "value": {"test": "HbA1c", "value": "7.2", "unit": "%", "reference_range": "<5.7", "abnormal": true},
      "confidence": 0.96,
      "evidence_text": "HbA1c 7.2% (reference <5.7%)"
    }
  ]
}

Text to analyze:
"""
    
    if retry_count > 0:
        prompt += "\n\nIMPORTANT: Previous attempt failed. Return ONLY valid JSON with no extra text.\n\n"
    
    prompt += f"\n{text}\n\nJSON output:"
    
    llm = LLMClient()
    response = llm.generate_response(prompt)
    
    # Clean response - remove markdown code blocks if present
    response = response.strip()
    if response.startswith("```"):
        # Remove markdown code fences
        response = re.sub(r'^```(?:json)?\s*\n', '', response)
        response = re.sub(r'\n```\s*$', '', response)
    
    # Parse JSON
    data = json.loads(response)
    
    # Convert to internal format with proper IDs and evidence spans
    candidates = []
    for fact in data.get("facts", []):
        fact_id = str(uuid4())[:8]
        fact_type = fact.get("fact_type", "unknown")
        value = fact.get("value", {})
        confidence = fact.get("confidence", 0.5)
        evidence_text = fact.get("evidence_text", "")
        
        # Create evidence span (will be refined later)
        evidence_span = {
            "source": chunks[0].get("source", "transcript") if chunks else "transcript",
            "source_id": chunks[0].get("source_id", "unknown") if chunks else "unknown",
            "locator": {},
            "snippet": evidence_text[:200],
            "strength": confidence
        }
        
        candidate = {
            "fact_id": fact_id,
            "type": fact_type,
            "value": value,
            "confidence": confidence,
            "provenance": {"evidence": [evidence_span]},
            "normalized": False,
            "conflict_group": None
        }
        candidates.append(candidate)
    
    return candidates


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


def _create_fallback_candidates(chunks: List[Dict]) -> List[Dict[str, Any]]:
    """Create low-confidence fallback candidates when LLM extraction fails."""
    candidates = []
    
    for chunk in chunks:
        text = chunk.get("text", "").lower()
        
        # Simple regex-based extraction as fallback
        # Medications: look for common drug names
        for canonical_name, aliases in MEDICATION_ALIASES.items():
            for alias in aliases:
                if alias in text:
                    candidates.append({
                        "fact_id": str(uuid4())[:8],
                        "type": "medication",
                        "value": {"name": canonical_name},
                        "confidence": 0.3,
                        "provenance": {"evidence": [{
                            "source": chunk.get("source", "transcript"),
                            "source_id": chunk.get("source_id", "unknown"),
                            "locator": {},
                            "snippet": text[:100],
                            "strength": 0.3
                        }]},
                        "normalized": True,
                        "conflict_group": None
                    })
                    break
    
    return candidates


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
