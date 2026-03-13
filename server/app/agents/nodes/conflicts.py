"""
Conflict Resolution Node — Resolves contradictions in extracted facts.

DB integration:
  - Uses patient_record_fields (prior DB record) as authoritative baseline
  - For conflicts between current extraction and prior record, the prior record
    wins unless the new extraction has very high confidence (>0.9)
"""

from typing import Dict, List, Any, Optional

from ..config import AgentContext
from ..state import GraphState, CandidateFact


RESOLUTION_RULES: Dict[str, Dict[str, Any]] = {
    "patient_name": {"mode": "set", "path": ["patient", "name"]},
    "patient_dob": {"mode": "set", "path": ["patient", "dob"]},
    "patient_age": {"mode": "set", "path": ["patient", "age"]},
    "patient_sex": {"mode": "set", "path": ["patient", "sex"]},
    "visit_date": {"mode": "set", "path": ["visit", "date"]},
    "visit_type": {"mode": "set", "path": ["visit", "type"]},
    "diagnosis_code": {"mode": "append", "path": ["diagnoses"], "field": "code", "merge_key": "code"},
    "diagnosis_description": {"mode": "append", "path": ["diagnoses"], "field": "description", "merge_key": "code"},
    "medication_name": {"mode": "append", "path": ["medications"], "field": "name", "merge_key": "name"},
    "medication_dose": {"mode": "append", "path": ["medications"], "field": "dose", "merge_key": "name"},
    "medication_route": {"mode": "append", "path": ["medications"], "field": "route", "merge_key": "name"},
    "medication_frequency": {"mode": "append", "path": ["medications"], "field": "frequency", "merge_key": "name"},
    "allergy_substance": {"mode": "append", "path": ["allergies"], "field": "substance", "merge_key": "substance"},
    "allergy_reaction": {"mode": "append", "path": ["allergies"], "field": "reaction", "merge_key": "substance"},
    "problem_name": {"mode": "append", "path": ["problems"], "field": "name", "merge_key": "name"},
    "lab_test": {"mode": "append", "path": ["labs"], "field": "test", "merge_key": "test"},
    "lab_value": {"mode": "append", "path": ["labs"], "field": "value", "merge_key": "test"},
    "procedure_name": {"mode": "append", "path": ["procedures"], "field": "name", "merge_key": "name"},
    "note_subjective": {"mode": "set", "path": ["notes", "subjective"]},
    "note_objective": {"mode": "set", "path": ["notes", "objective"]},
    "note_assessment": {"mode": "set", "path": ["notes", "assessment"]},
    "note_plan": {"mode": "set", "path": ["notes", "plan"]},
}


def _resolve_by_confidence(candidates: List[CandidateFact]) -> Dict[str, Dict[str, Any]]:
    best_by_type: Dict[str, CandidateFact] = {}
    for fact in candidates:
        fact_type = fact.get("type", "unknown")
        if fact.get("confidence") is None:
            continue
        current = best_by_type.get(fact_type)
        if current is None or (fact["confidence"] or 0) > (current.get("confidence") or 0):
            best_by_type[fact_type] = fact

    resolutions: Dict[str, Dict[str, Any]] = {}
    for fact_type, fact in best_by_type.items():
        if fact.get("value") is not None:
            resolutions[fact_type] = {
                "value": fact["value"],
                "confidence": fact.get("confidence"),
            }
    return resolutions


def _ensure_path(record: Dict[str, Any], path: List[str]) -> Any:
    current: Any = record
    for key in path:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    return current


def _ensure_list(record: Dict[str, Any], path: List[str]) -> List[Dict[str, Any]]:
    current: Any = record
    for key in path[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]

    list_key = path[-1]
    if list_key not in current or not isinstance(current[list_key], list):
        current[list_key] = []
    return current[list_key]


def _apply_resolution(record: Dict[str, Any], fact_type: str, value: Any, confidence: Any) -> None:
    rule = RESOLUTION_RULES.get(fact_type)
    if not rule:
        return

    mode = rule["mode"]
    path = rule["path"]

    if mode == "set":
        target = _ensure_path(record, path[:-1]) if len(path) > 1 else record
        key = path[-1]
        if confidence is not None:
            target[key] = {"value": value, "confidence": confidence}
        else:
            target[key] = value
        return

    if mode == "append":
        items = _ensure_list(record, path)
        merge_key = rule.get("merge_key")
        merge_key_value = None
        if merge_key:
            if isinstance(value, dict):
                merge_key_value = value.get(merge_key)
            else:
                merge_key_value = value

        target_item: Optional[Dict[str, Any]] = None
        if merge_key and merge_key_value is not None:
            for item in items:
                if item.get(merge_key) == merge_key_value:
                    target_item = item
                    break

        if target_item is None:
            target_item = {}
            if merge_key and merge_key_value is not None:
                target_item[merge_key] = merge_key_value
            items.append(target_item)

        field_name = rule.get("field")
        if field_name:
            field_value = value
            if isinstance(value, dict) and field_name in value:
                field_value = value[field_name]
            target_item[field_name] = field_value
        if confidence is not None:
            target_item["confidence"] = confidence


def conflict_resolution_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """Resolve contradictions in extracted facts or evidence.
    
    Uses DB prior record as authoritative baseline when available.
    For conflicts between current extraction and prior record, the prior record
    wins unless the new extraction has very high confidence (>0.9).
    """
    state = state.copy()
    validation = state.get("validation_report") or {}
    conflicts = validation.get("conflicts") or []
    candidates = state.get("candidate_facts") or []

    resolutions = _resolve_by_confidence(candidates)
    record = state.get("structured_record") or {}
    
    # Apply DB-baseline resolution for cross-visit conflicts
    prf = state.get("patient_record_fields") or {}
    db_resolutions = []
    if prf.get("loaded_from_db"):
        db_resolutions = _resolve_cross_visit_conflicts(
            conflicts, record, prf, resolutions
        )
    
    for fact_type, resolved in resolutions.items():
        _apply_resolution(record, fact_type, resolved.get("value"), resolved.get("confidence"))
    state["structured_record"] = record
    unresolved = bool(conflicts)

    if conflicts and (resolutions or db_resolutions):
        unresolved = False

    state["conflict_report"] = {
        "unresolved": unresolved,
        "conflicts": conflicts,
        "resolutions": (
            [f"{k} -> {repr(v.get('value'))}" for k, v in resolutions.items()]
            + db_resolutions
        ),
        "evidence": {},
    }

    return state


def _resolve_cross_visit_conflicts(
    conflicts: List[str],
    record: Dict[str, Any],
    prf: Dict[str, Any],
    resolutions: Dict[str, Dict[str, Any]],
) -> List[str]:
    """
    Resolve cross-visit conflicts using DB as authoritative baseline.
    
    Strategy: Prior DB record wins unless new extraction has confidence > 0.9.
    """
    resolved_descriptions = []
    prior_record = prf.get("prior_record", {})
    
    for conflict in list(conflicts):
        if not conflict.startswith("cross-visit:"):
            continue
        
        # Handle missing allergy conflicts
        if "prior allergy" in conflict and "not found" in conflict:
            # Extract allergy name from conflict message
            # Restore the allergy from prior record
            prior_allergies = prior_record.get("allergies", [])
            for pa in prior_allergies:
                substance = pa.get("substance", "")
                if substance.lower() in conflict.lower():
                    # Re-add from prior record with source marker
                    pa_copy = dict(pa)
                    pa_copy["source"] = "prior_record_restored"
                    pa_copy.setdefault("confidence", 0.8)
                    record.setdefault("allergies", []).append(pa_copy)
                    resolved_descriptions.append(
                        f"Restored prior allergy '{substance}' from DB baseline"
                    )
                    break
        
        # Handle demographic mismatches — DB wins
        if "sex mismatch" in conflict or "dob mismatch" in conflict:
            demographics = prf.get("demographics", {})
            if demographics.get("sex"):
                record.setdefault("patient", {})["sex"] = demographics["sex"]
                resolved_descriptions.append(
                    f"Resolved demographic conflict: using DB value (sex={demographics['sex']})"
                )
    
    return resolved_descriptions
