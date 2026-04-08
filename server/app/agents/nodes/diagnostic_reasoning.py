"""
Agent B+ -- Diagnostic Reasoning Node.

Purpose: Analyze extracted candidate facts to produce structured diagnostic
intelligence: differential diagnoses with confidence, recommended
tests/workup, risk flags, and treatment guidance.

Pipeline position: Runs AFTER extract_candidates and BEFORE retrieve_evidence.
This gives the evidence retrieval node richer queries to ground against.

Inputs (from state):
    candidate_facts    -- extracted clinical entities from Agent B
    structured_record  -- partially filled record (demographics, vitals, etc.)
    patient_record_fields -- prior history loaded from DB

Outputs (written to state):
    diagnostic_reasoning -- dict with top diagnoses, recommended tests,
                            risk flags, treatment guidance, and reasoning trace
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..config import AgentContext
from ..state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Specialty detection heuristics
# ---------------------------------------------------------------------------

_SPECIALTY_KEYWORDS: Dict[str, List[str]] = {
    "cardiology": [
        "chest pain", "palpitations", "hypertension", "murmur", "arrhythmia",
        "atrial fibrillation", "heart failure", "angina", "myocardial",
        "echocardiogram", "troponin", "bnp", "stemi", "nstemi",
    ],
    "endocrinology": [
        "diabetes", "thyroid", "hba1c", "insulin", "glucose", "tsh",
        "hyperthyroidism", "hypothyroidism", "adrenal", "pituitary",
        "metformin", "hemoglobin a1c",
    ],
    "pulmonology": [
        "shortness of breath", "dyspnea", "cough", "wheezing", "copd",
        "asthma", "pneumonia", "spo2", "oxygen", "pulmonary",
    ],
    "gastroenterology": [
        "abdominal pain", "nausea", "vomiting", "diarrhea", "constipation",
        "gerd", "reflux", "liver", "hepatitis", "cirrhosis", "pancreatitis",
    ],
    "neurology": [
        "headache", "seizure", "numbness", "tingling", "stroke", "tia",
        "weakness", "dizziness", "vertigo", "neuropathy", "dementia",
    ],
    "nephrology": [
        "creatinine", "egfr", "kidney", "renal", "dialysis", "proteinuria",
        "hematuria", "glomerular",
    ],
    "rheumatology": [
        "joint pain", "arthritis", "lupus", "rheumatoid", "gout",
        "autoimmune", "inflammation", "sed rate", "ana", "uric acid",
    ],
    "infectious_disease": [
        "fever", "infection", "sepsis", "antibiotic", "culture", "wbc",
        "leukocytosis", "abscess",
    ],
    "hematology": [
        "anemia", "bleeding", "clotting", "platelet", "hemoglobin",
        "transfusion", "coagulation", "inr", "warfarin",
    ],
    "psychiatry": [
        "depression", "anxiety", "insomnia", "suicidal", "psychosis",
        "bipolar", "ssri", "mood", "hallucination",
    ],
}

# ---------------------------------------------------------------------------
# Common diagnostic patterns (rule-based fallback when LLM unavailable)
# ---------------------------------------------------------------------------

_DIAGNOSTIC_PATTERNS: Dict[str, Dict[str, Any]] = {
    "chest_pain_cardiac": {
        "triggers": ["chest pain", "angina", "substernal"],
        "require_any": ["hypertension", "diabetes", "smoking", "hyperlipidemia",
                        "family history", "troponin", "ecg"],
        "diagnoses": [
            {"name": "Acute Coronary Syndrome", "icd10": "I21.9", "confidence": 0.65},
            {"name": "Unstable Angina", "icd10": "I20.0", "confidence": 0.55},
            {"name": "Stable Angina Pectoris", "icd10": "I20.8", "confidence": 0.50},
        ],
        "recommended_tests": [
            "12-lead ECG", "Troponin I/T (serial)", "CBC", "BMP",
            "Chest X-ray", "Lipid panel",
        ],
        "risk_flags": ["Cardiac risk factors present"],
    },
    "diabetes_management": {
        "triggers": ["diabetes", "hba1c", "glucose", "metformin", "insulin"],
        "require_any": [],
        "diagnoses": [
            {"name": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "confidence": 0.75},
        ],
        "recommended_tests": [
            "HbA1c", "Fasting glucose", "Lipid panel", "BMP (creatinine, eGFR)",
            "Urine microalbumin/creatinine ratio", "Dilated eye exam referral",
        ],
        "risk_flags": ["Monitor for diabetic complications"],
    },
    "hypertension": {
        "triggers": ["hypertension", "high blood pressure", "elevated bp"],
        "require_any": [],
        "diagnoses": [
            {"name": "Essential Hypertension", "icd10": "I10", "confidence": 0.80},
        ],
        "recommended_tests": [
            "BMP (electrolytes, creatinine)", "Lipid panel", "Urinalysis",
            "ECG", "Echocardiogram if sustained",
        ],
        "risk_flags": ["Cardiovascular risk factor"],
    },
    "respiratory_infection": {
        "triggers": ["cough", "fever", "sore throat", "congestion"],
        "require_any": ["wbc", "respiratory", "sputum", "pneumonia"],
        "diagnoses": [
            {"name": "Upper Respiratory Infection", "icd10": "J06.9", "confidence": 0.70},
            {"name": "Acute Bronchitis", "icd10": "J20.9", "confidence": 0.50},
            {"name": "Community-Acquired Pneumonia", "icd10": "J18.9", "confidence": 0.40},
        ],
        "recommended_tests": [
            "Chest X-ray", "CBC with differential", "Rapid strep test",
            "Influenza/COVID rapid test", "Sputum culture if productive",
        ],
        "risk_flags": [],
    },
}


# ---------------------------------------------------------------------------
# Public node function
# ---------------------------------------------------------------------------

def diagnostic_reasoning_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Analyze candidate facts to produce diagnostic intelligence.

    Writes ``state["diagnostic_reasoning"]`` with:
        - top_diagnoses: ranked list with confidence + reasoning
        - recommended_tests: ordered workup suggestions
        - risk_flags: clinical risk alerts
        - treatment_guidance: initial treatment direction
        - specialty: detected medical specialty
        - reasoning_trace: step-by-step reasoning narrative
    """
    state = state.copy() if isinstance(state, dict) else state

    candidate_facts = state.get("candidate_facts", [])
    structured_record = state.get("structured_record", {})
    patient_fields = state.get("patient_record_fields") or {}
    controls = state.get("controls", {"attempts": {}, "budget": {}, "trace_log": []})
    trace = controls.setdefault("trace_log", [])

    trace.append({
        "node": "diagnostic_reasoning",
        "action": "started",
        "candidate_count": len(candidate_facts),
        "timestamp": datetime.now().isoformat(),
    })

    # Guard: nothing to reason about
    if not candidate_facts and not structured_record:
        reasoning = _empty_reasoning("No candidate facts or record available")
        state["diagnostic_reasoning"] = reasoning
        trace.append({
            "node": "diagnostic_reasoning",
            "action": "skipped",
            "reason": "empty_input",
            "timestamp": datetime.now().isoformat(),
        })
        return state

    # Build a clinical summary from candidates + record
    clinical_summary = _build_clinical_summary(candidate_facts, structured_record, patient_fields)
    specialty = _detect_specialty(clinical_summary)

    # Budget check
    budget = controls.get("budget", {})
    max_llm_calls = budget.get("max_total_llm_calls", ctx.max_llm_calls if ctx else 30)
    llm_calls_used = budget.get("llm_calls_used", 0)

    reasoning: Dict[str, Any]

    if llm_calls_used < max_llm_calls and ctx:
        # LLM-powered diagnostic reasoning
        try:
            llm = ctx.llm if ctx.llm else (ctx.llm_factory() if ctx.llm_factory else None)
            if llm is None:
                raise RuntimeError("No LLM client available")
            llm_calls_used += 1
            reasoning = _llm_diagnostic_reasoning(llm, clinical_summary, specialty)
            reasoning["method"] = "llm"
        except Exception as exc:
            logger.warning("LLM diagnostic reasoning failed, falling back to rules: %s", exc)
            reasoning = _rule_based_reasoning(clinical_summary, specialty)
            reasoning["method"] = "rule_fallback"
    else:
        # Rule-based fallback
        reasoning = _rule_based_reasoning(clinical_summary, specialty)
        reasoning["method"] = "rule_based"

    reasoning["specialty"] = specialty
    reasoning["clinical_summary"] = clinical_summary

    # Update budget
    budget["llm_calls_used"] = llm_calls_used
    controls["budget"] = budget

    trace.append({
        "node": "diagnostic_reasoning",
        "action": "completed",
        "method": reasoning["method"],
        "diagnosis_count": len(reasoning.get("top_diagnoses", [])),
        "test_count": len(reasoning.get("recommended_tests", [])),
        "risk_flag_count": len(reasoning.get("risk_flags", [])),
        "specialty": specialty,
        "timestamp": datetime.now().isoformat(),
    })

    state["diagnostic_reasoning"] = reasoning
    state["controls"] = controls

    logger.info(
        "[Diagnostic Reasoning] %s: %d diagnoses, %d tests, %d risk flags (method=%s)",
        specialty,
        len(reasoning.get("top_diagnoses", [])),
        len(reasoning.get("recommended_tests", [])),
        len(reasoning.get("risk_flags", [])),
        reasoning["method"],
    )

    return state


# ---------------------------------------------------------------------------
# Clinical summary builder
# ---------------------------------------------------------------------------

def _build_clinical_summary(
    candidates: List[Dict[str, Any]],
    record: Dict[str, Any],
    patient_fields: Dict[str, Any],
) -> str:
    """Assemble a prose summary of all available clinical data."""
    parts: List[str] = []

    # Demographics
    demo = record.get("demographics") or {}
    age = demo.get("age") or ""
    sex = demo.get("sex") or ""
    if age or sex:
        parts.append(f"Patient: {age} {sex}".strip() + ".")

    # Chief complaint
    cc = record.get("chief_complaint") or {}
    if cc.get("free_text"):
        onset = f", onset {cc['onset']}" if cc.get("onset") else ""
        severity = f", severity {cc['severity']}" if cc.get("severity") else ""
        parts.append(f"Chief complaint: {cc['free_text']}{onset}{severity}.")

    # HPI events
    hpi = record.get("hpi", [])
    if hpi:
        symptoms = [e.get("symptom", "") for e in hpi if e.get("symptom")]
        if symptoms:
            parts.append(f"HPI symptoms: {', '.join(symptoms)}.")

    # Vitals
    vitals = record.get("vitals") or {}
    vital_items = []
    for key in ("blood_pressure", "heart_rate", "temperature", "spo2", "respiratory_rate"):
        val = vitals.get(key)
        if val:
            vital_items.append(f"{key.replace('_', ' ')}: {val}")
    if vital_items:
        parts.append(f"Vitals: {'; '.join(vital_items)}.")

    # Medications
    meds = record.get("medications", [])
    if meds:
        med_names = [m.get("name", "?") for m in meds[:10]]
        parts.append(f"Current medications: {', '.join(med_names)}.")

    # Allergies
    allergies = record.get("allergies", [])
    if allergies:
        allergy_names = [a.get("substance", "?") for a in allergies]
        parts.append(f"Allergies: {', '.join(allergy_names)}.")

    # Chronic conditions
    pmh = record.get("past_medical_history") or {}
    chronic = pmh.get("chronic_conditions", [])
    if chronic:
        cond_names = [c.get("name", "?") for c in chronic]
        parts.append(f"Chronic conditions: {', '.join(cond_names)}.")

    # Labs
    labs = record.get("labs", [])
    if labs:
        abnormal = [lb for lb in labs if lb.get("abnormal")]
        if abnormal:
            lab_strs = [f"{lb.get('test','?')}: {lb.get('value','?')} {lb.get('unit','')}"
                        for lb in abnormal[:8]]
            parts.append(f"Abnormal labs: {'; '.join(lab_strs)}.")

    # Additional candidate fact types not yet in structured_record
    for fact in candidates:
        ft = fact.get("fact_type") or fact.get("type", "")
        if ft in ("diagnosis", "assessment", "risk_factor"):
            val = fact.get("value", "")
            if isinstance(val, dict):
                desc = val.get("description") or val.get("name") or str(val)
            else:
                desc = str(val)
            parts.append(f"Candidate {ft}: {desc}.")

    # Prior history from DB
    prior_facts = patient_fields.get("prior_facts", {})
    for fact_type, facts in prior_facts.items():
        if facts:
            keys = [f.get("fact_key", "?") for f in facts[:4]]
            parts.append(f"Prior {fact_type}: {', '.join(keys)}.")

    return " ".join(parts) if parts else "Insufficient clinical data."


# ---------------------------------------------------------------------------
# Specialty detection
# ---------------------------------------------------------------------------

def _detect_specialty(clinical_summary: str) -> str:
    """Detect the most likely medical specialty from clinical text."""
    text_lower = clinical_summary.lower()
    scores: Dict[str, int] = {}
    for specialty, keywords in _SPECIALTY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[specialty] = score

    if not scores:
        return "general_medicine"

    return max(scores, key=scores.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LLM-based diagnostic reasoning
# ---------------------------------------------------------------------------

def _llm_diagnostic_reasoning(
    llm: Any,
    clinical_summary: str,
    specialty: str,
) -> Dict[str, Any]:
    """Use LLM to produce structured diagnostic reasoning."""
    prompt = f"""You are an expert clinical diagnostician specializing in {specialty.replace('_', ' ')}.

Analyze the following clinical presentation and provide structured diagnostic reasoning.

CLINICAL PRESENTATION:
{clinical_summary}

Return ONLY valid JSON with this exact structure:
{{
  "top_diagnoses": [
    {{
      "name": "Diagnosis name",
      "icd10": "ICD-10 code or null",
      "confidence": 0.0-1.0,
      "reasoning": "Brief clinical reasoning for this diagnosis",
      "supporting_evidence": ["evidence item 1", "evidence item 2"],
      "against_evidence": ["finding that argues against"]
    }}
  ],
  "recommended_tests": [
    {{
      "test": "Test name",
      "rationale": "Why this test is recommended",
      "priority": "stat|urgent|routine",
      "expected_finding": "What result would support/refute diagnosis"
    }}
  ],
  "risk_flags": [
    {{
      "flag": "Risk description",
      "severity": "critical|high|moderate|low",
      "action": "Recommended action"
    }}
  ],
  "treatment_guidance": [
    {{
      "condition": "Target condition",
      "recommendation": "Treatment recommendation",
      "evidence_level": "guideline|expert_consensus|empiric",
      "precautions": ["precaution 1"]
    }}
  ],
  "reasoning_trace": "Step-by-step narrative of the diagnostic reasoning process"
}}

Rules:
- Provide 3-5 differential diagnoses ranked by likelihood
- Include at least 3 recommended tests with clear rationale
- Flag any critical or time-sensitive findings
- Base treatment guidance on current clinical guidelines
- Do NOT fabricate clinical data not present in the summary
"""

    response = llm.generate_response(prompt, max_tokens=1500).strip()

    # Strip markdown fences
    if response.startswith("```"):
        response = re.sub(r"^```(?:json)?\s*\n?", "", response)
        response = re.sub(r"\n?```\s*$", "", response)

    try:
        result = json.loads(response)
        if not isinstance(result, dict):
            return _empty_reasoning("LLM returned non-dict")
        # Validate required keys
        for key in ("top_diagnoses", "recommended_tests", "risk_flags"):
            if key not in result:
                result[key] = []
        if "treatment_guidance" not in result:
            result["treatment_guidance"] = []
        if "reasoning_trace" not in result:
            result["reasoning_trace"] = ""
        return result
    except json.JSONDecodeError:
        logger.warning("Diagnostic reasoning LLM returned invalid JSON")
        return _empty_reasoning("LLM JSON parse failure")


# ---------------------------------------------------------------------------
# Rule-based fallback reasoning
# ---------------------------------------------------------------------------

def _rule_based_reasoning(
    clinical_summary: str,
    specialty: str,
) -> Dict[str, Any]:
    """Produce diagnostic reasoning using pattern-matching rules."""
    text_lower = clinical_summary.lower()

    matched_diagnoses: List[Dict[str, Any]] = []
    matched_tests: List[Dict[str, Any]] = []
    matched_risk_flags: List[Dict[str, Any]] = []
    matched_treatments: List[Dict[str, Any]] = []

    for pattern_name, pattern in _DIAGNOSTIC_PATTERNS.items():
        # Check if any trigger is present
        trigger_hit = any(t in text_lower for t in pattern["triggers"])
        if not trigger_hit:
            continue

        # Add diagnoses
        for dx in pattern["diagnoses"]:
            if not any(d["name"] == dx["name"] for d in matched_diagnoses):
                matched_diagnoses.append({
                    "name": dx["name"],
                    "icd10": dx.get("icd10"),
                    "confidence": dx["confidence"],
                    "reasoning": f"Clinical presentation includes: {', '.join(t for t in pattern['triggers'] if t in text_lower)}",
                    "supporting_evidence": [t for t in pattern["triggers"] if t in text_lower],
                    "against_evidence": [],
                })

        # Add tests
        for test_name in pattern["recommended_tests"]:
            if not any(t["test"] == test_name for t in matched_tests):
                matched_tests.append({
                    "test": test_name,
                    "rationale": f"Indicated for workup of {pattern['diagnoses'][0]['name'] if pattern['diagnoses'] else 'unknown'}",
                    "priority": "routine",
                    "expected_finding": "",
                })

        # Add risk flags
        for flag_text in pattern.get("risk_flags", []):
            matched_risk_flags.append({
                "flag": flag_text,
                "severity": "moderate",
                "action": "Monitor and reassess",
            })

    # Add general screenings based on demographics
    if "diabetes" in text_lower or "metformin" in text_lower:
        matched_treatments.append({
            "condition": "Type 2 Diabetes Mellitus",
            "recommendation": "Continue current antidiabetic regimen; target HbA1c < 7%",
            "evidence_level": "guideline",
            "precautions": ["Monitor renal function with metformin"],
        })
    if "hypertension" in text_lower:
        matched_treatments.append({
            "condition": "Essential Hypertension",
            "recommendation": "Target BP < 130/80 mmHg per ACC/AHA guidelines",
            "evidence_level": "guideline",
            "precautions": ["Monitor electrolytes with ACE-I/ARB/diuretic"],
        })

    # Build reasoning trace
    if matched_diagnoses:
        trace_parts = [f"Identified {len(matched_diagnoses)} potential diagnoses based on clinical presentation."]
        for dx in matched_diagnoses:
            trace_parts.append(f"- {dx['name']}: supported by {', '.join(dx['supporting_evidence'])}.")
        reasoning_trace = " ".join(trace_parts)
    else:
        reasoning_trace = "Insufficient pattern matches for rule-based diagnosis. Consider LLM-based analysis."

    return {
        "top_diagnoses": matched_diagnoses,
        "recommended_tests": matched_tests,
        "risk_flags": matched_risk_flags,
        "treatment_guidance": matched_treatments,
        "reasoning_trace": reasoning_trace,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_reasoning(reason: str) -> Dict[str, Any]:
    """Return an empty diagnostic reasoning structure."""
    return {
        "top_diagnoses": [],
        "recommended_tests": [],
        "risk_flags": [],
        "treatment_guidance": [],
        "reasoning_trace": reason,
        "method": "none",
        "specialty": "general_medicine",
        "clinical_summary": "",
    }
