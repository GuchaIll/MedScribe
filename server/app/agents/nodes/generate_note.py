"""
Agent H — Note Generator (Grounded)

Purpose: Produce human-readable clinical note grounded in structured record.
Hard constraint: No new entities not present in record. SOAP/H&P format.
Tools: LLM summarizer with strict grounding ("use only provided JSON")

DB integration:
  - Includes patient history context (visit count, prior problems) in prompt
  - Flags facts with low grounding scores
"""

import json
from typing import Dict, Any, Optional
from ..config import AgentContext
from ..state import GraphState
from ...models.llm import LLMClient


def generate_note_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Generate clinical note from structured record only (no hallucinating).
    
    Agent H: Note Generator
    - Produces SOAP (Subjective/Objective/Assessment/Plan) format note
    - Grounded ONLY in structured_record (no access to raw transcripts)
    - Includes patient history context paragraph (visit count, prior facts)
    - Includes warnings/conflicts section if present
    - LLM constrained to not add concepts not in record
    """
    state = state.copy() if isinstance(state, dict) else state
    
    record = state.get("structured_record", {})
    validation = state.get("validation_report", {})
    conflicts = state.get("conflict_report", {})
    
    if not record or not record.get("patient"):
        state["clinical_note"] = "Unable to generate note: No patient data available."
        return state
    
    # Check budget
    controls = state.get("controls", {"attempts": {}, "budget": {}})
    budget = controls.get("budget", {})
    max_llm_calls = budget.get("max_total_llm_calls", ctx.max_llm_calls if ctx else 30)
    llm_calls_used = budget.get("llm_calls_used", 0)
    
    if llm_calls_used >= max_llm_calls:
        state["clinical_note"] = _generate_template_note(record, validation, conflicts)
        print("[Generate Note] Budget exhausted, using template-based note")
        return state
    
    # Generate note using LLM with strict grounding
    try:
        llm = LLMClient()
        llm_calls_used += 1
        
        # Build patient history context for the note
        history_context = _build_history_context(state)
        
        note = _generate_llm_note(llm, record, validation, conflicts, history_context)
        state["clinical_note"] = note
        
        # Update budget
        budget["llm_calls_used"] = llm_calls_used
        controls["budget"] = budget
        state["controls"] = controls
        
        print(f"[Generate Note] Created SOAP note ({len(note)} chars, LLM calls: {llm_calls_used}/{max_llm_calls})")
        
    except Exception as e:
        print(f"[Generate Note] Error: {e}")
        state["clinical_note"] = _generate_template_note(record, validation, conflicts)
        print("[Generate Note] Using template-based note as fallback")
    
    # Track node execution
    controls["attempts"]["generate_note"] = \
        controls.get("attempts", {}).get("generate_note", 0) + 1
    
    return state


def _generate_llm_note(llm: LLMClient, record: Dict, validation: Dict, 
                       conflicts: Dict, history_context: str = "") -> str:
    """Generate note using LLM with strict grounding constraints."""
    
    # Serialize record to JSON for grounding
    record_json = json.dumps(record, indent=2, default=str)
    
    prompt = f"""You are a medical documentation assistant. Generate a clinical note in SOAP format.

CRITICAL CONSTRAINTS:
1. Use ONLY information from the provided JSON record
2. Do NOT add any clinical facts not present in the record
3. Do NOT infer diagnoses or treatments not explicitly stated
4. If information is missing, state "Not documented" rather than inventing
5. Include confidence warnings for low-confidence fields
"""

    if history_context:
        prompt += f"""
PATIENT HISTORY CONTEXT:
{history_context}
Include a brief "History" section at the top of the note summarizing relevant prior visits.
"""

    prompt += f"""
Format: SOAP Note
- Subjective: Patient reported symptoms/history
- Objective: Vitals, labs, physical findings
- Assessment: Diagnoses and clinical interpretation
- Plan: Medications, procedures, follow-up

Structured Record (USE ONLY THIS DATA):
{record_json}

Generate a professional SOAP note using ONLY the above data:"""
    
    response = llm.generate_response(prompt)
    
    # Add warnings section if there are validation issues or conflicts
    warnings = []
    if validation.get("schema_errors"):
        warnings.append(f"⚠ Validation Issues: {len(validation['schema_errors'])} errors detected")
    if validation.get("needs_review"):
        warnings.append("⚠ This record requires clinical review")
    if conflicts.get("conflicts"):
        warnings.append(f"⚠ Conflicts Detected: {len(conflicts.get('conflicts', []))} unresolved")
    
    if warnings:
        response += "\n\n--- SYSTEM WARNINGS ---\n" + "\n".join(warnings)
    
    return response


def _generate_template_note(record: Dict, validation: Dict, conflicts: Dict) -> str:
    """Generate deterministic template-based note (no LLM)."""
    
    patient = record.get("patient", {})
    allergies = record.get("allergies", [])
    medications = record.get("medications", [])
    diagnoses = record.get("diagnoses", [])
    vitals = record.get("vitals", [])
    labs = record.get("labs", [])
    procedures = record.get("procedures", [])
    followups = record.get("followups", [])
    
    lines = []
    lines.append("CLINICAL NOTE")
    lines.append("=" * 60)
    lines.append("")
    
    # Header
    lines.append("PATIENT INFORMATION")
    lines.append(f"Name: {patient.get('name', 'Not documented')}")
    lines.append(f"DOB: {patient.get('dob', 'Not documented')}")
    lines.append(f"Age: {patient.get('age', 'Not documented')}")
    lines.append(f"Sex: {patient.get('sex', 'Not documented')}")
    if patient.get("mrn"):
        lines.append(f"MRN: {patient['mrn']}")
    lines.append("")
    
    # Allergies
    lines.append("ALLERGIES")
    if allergies:
        for allergy in allergies:
            substance = allergy.get("substance", "Unknown")
            reaction = allergy.get("reaction", "")
            conf = allergy.get("confidence", 0)
            line = f"  • {substance}"
            if reaction:
                line += f" - {reaction}"
            if conf < 0.7:
                line += f" (confidence: {conf:.0%})"
            lines.append(line)
    else:
        lines.append("  None documented")
    lines.append("")
    
    # Subjective
    lines.append("SUBJECTIVE")
    lines.append("  Patient presented for clinical evaluation.")
    if record.get("notes", {}).get("subjective"):
        lines.append(f"  {record['notes']['subjective']}")
    else:
        lines.append("  Details from transcript: See source documentation")
    lines.append("")
    
    # Objective
    lines.append("OBJECTIVE")
    
    # Vitals
    if vitals:
        lines.append("  Vitals:")
        for vital in vitals:
            v_type = vital.get("type", "Unknown")
            value = vital.get("value", "")
            unit = vital.get("unit", "")
            lines.append(f"    {v_type}: {value} {unit}".strip())
    
    # Labs
    if labs:
        lines.append("  Laboratory Results:")
        for lab in labs:
            test = lab.get("test", "Unknown")
            value = lab.get("value", "")
            unit = lab.get("unit", "")
            ref_range = lab.get("reference_range", "")
            line = f"    {test}: {value} {unit}".strip()
            if ref_range:
                line += f" (ref: {ref_range})"
            lines.append(line)
    
    if not vitals and not labs:
        lines.append("  No objective findings documented")
    lines.append("")
    
    # Assessment
    lines.append("ASSESSMENT")
    if diagnoses:
        for dx in diagnoses:
            code = dx.get("code", "")
            desc = dx.get("description", "")
            conf = dx.get("confidence", 0)
            line = f"  • "
            if code:
                line += f"[{code}] "
            line += desc if desc else "Diagnosis documented"
            if conf < 0.7:
                line += f" (confidence: {conf:.0%})"
            lines.append(line)
    else:
        lines.append("  No diagnoses documented")
    lines.append("")
    
    # Plan
    lines.append("PLAN")
    
    # Medications
    if medications:
        lines.append("  Medications:")
        for med in medications:
            name = med.get("name", "Unknown")
            dose = med.get("dose", "")
            route = med.get("route", "")
            freq = med.get("frequency", "")
            line = f"    • {name}"
            if dose:
                line += f" {dose}"
            if route:
                line += f" {route}"
            if freq:
                line += f" {freq}"
            lines.append(line)
    
    # Procedures
    if procedures:
        lines.append("  Procedures:")
        for proc in procedures:
            name = proc.get("name", "Unknown")
            date = proc.get("date", "")
            line = f"    • {name}"
            if date:
                line += f" (scheduled: {date})"
            lines.append(line)
    
    # Follow-up
    if followups:
        lines.append("  Follow-up:")
        for fu in followups:
            if isinstance(fu, dict):
                desc = fu.get("description", str(fu))
                timeframe = fu.get("timeframe", "")
                line = f"    • {desc}"
                if timeframe:
                    line += f" ({timeframe})"
                lines.append(line)
            else:
                lines.append(f"    • {fu}")
    
    if not medications and not procedures and not followups:
        lines.append("  No treatment plan documented")
    lines.append("")
    
    # Warnings
    warnings = []
    if validation.get("schema_errors"):
        warnings.append(f"⚠ Validation Issues: {len(validation['schema_errors'])} errors detected")
    if validation.get("missing_fields"):
        warnings.append(f"⚠ Missing Required Fields: {', '.join(validation['missing_fields'][:3])}")
    if validation.get("needs_review"):
        warnings.append("⚠ This record requires clinical review")
    if conflicts.get("conflicts"):
        warnings.append(f"⚠ Conflicts Detected: {len(conflicts.get('conflicts', []))} unresolved")
    
    if warnings:
        lines.append("--- SYSTEM WARNINGS ---")
        lines.extend(warnings)
        lines.append("")
    
    lines.append("=" * 60)
    lines.append("Note generated from structured clinical record")
    
    return "\n".join(lines)


def _build_history_context(state: GraphState) -> str:
    """Build a patient history summary string for the LLM prompt."""
    prf = state.get("patient_record_fields") or {}
    if not prf.get("loaded_from_db"):
        return ""

    parts = []
    visit_count = prf.get("visit_count", 0)
    if visit_count > 0:
        parts.append(f"This is visit #{visit_count + 1} for this patient.")

    prior_facts = prf.get("prior_facts", {})
    for fact_type, facts in prior_facts.items():
        if facts:
            keys = [f.get("fact_key", "?") for f in facts[:5]]
            parts.append(f"Prior {fact_type}s: {', '.join(keys)}")

    demographics = prf.get("demographics", {})
    if demographics.get("full_name"):
        parts.append(f"Patient: {demographics['full_name']}")

    return "; ".join(parts) if parts else ""
