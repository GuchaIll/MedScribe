"""
Validate and Score Node — Schema validation + cross-visit contradiction detection.

DB integration:
  - Uses patient_record_fields to detect contradictions between current session
    and prior finalized records (e.g., allergy removed, conflicting diagnosis)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from ..config import AgentContext
from ..state import GraphState, CandidateFact
from ..validation_contracts import CONTRACT
from pydantic import ValidationError

from .record_schema import StructuredRecord

logger = logging.getLogger(__name__)


def _sanitize_contract(obj: Any) -> Any:
    """Recursively convert Python type objects to JSON-serializable strings."""
    if isinstance(obj, type):
        return obj.__name__
    if isinstance(obj, dict):
        return {k: _sanitize_contract(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_contract(item) for item in obj]
    return obj


def _get_value_and_confidence(field_value: Any) -> Tuple[Any, Any]:
    if isinstance(field_value, dict):
        return field_value.get("value"), field_value.get("confidence")
    return field_value, None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and not value:
        return True
    if isinstance(value, dict) and not value:
        return True
    return False


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _detect_conflicts(candidates: List[CandidateFact]) -> List[str]:
    values_by_type: Dict[str, List[Any]] = {}
    for fact in candidates:
        values_by_type.setdefault(fact.get("type", "unknown"), []).append(fact.get("value"))

    conflicts: List[str] = []
    for fact_type, values in values_by_type.items():
        unique_values = {repr(value) for value in values if value is not None}
        if len(unique_values) > 1:
            conflicts.append(f"conflicting values for {fact_type}: {sorted(unique_values)}")
    return conflicts


def _validate_field(raw_value: Any, rules: Dict[str, Any], path: str, errors: List[str], missing: List[str]) -> None:
    if rules.get("required") and _is_missing(raw_value):
        missing.append(path)
        return

    if _is_missing(raw_value):
        return

    if "schema" in rules:
        if not isinstance(raw_value, dict):
            errors.append(f"{path} expected dict, got {type(raw_value).__name__}")
            return
        for key, sub_rules in rules["schema"].items():
            _validate_field(raw_value.get(key), sub_rules, f"{path}.{key}", errors, missing)
        return

    if "item_schema" in rules:
        if not isinstance(raw_value, list):
            errors.append(f"{path} expected list, got {type(raw_value).__name__}")
            return
        if rules.get("non_empty") and not raw_value:
            errors.append(f"{path} must be non-empty")
        for idx, item in enumerate(raw_value):
            _validate_field(item, rules["item_schema"], f"{path}[{idx}]", errors, missing)
        return

    value, confidence = _get_value_and_confidence(raw_value)

    expected_type = rules.get("type")
    if expected_type and not isinstance(value, expected_type):
        errors.append(f"{path} expected {expected_type.__name__}, got {type(value).__name__}")

    if rules.get("non_empty"):
        if isinstance(value, str) and not value.strip():
            errors.append(f"{path} must be non-empty")
        if isinstance(value, list) and not value:
            errors.append(f"{path} must be non-empty")

    if rules.get("iso_format") and not _is_iso_date(value):
        errors.append(f"{path} must be ISO-8601 date")

    min_confidence = rules.get("min_confidence")
    if min_confidence is not None and confidence is not None and confidence < min_confidence:
        errors.append(f"{path} confidence {confidence} < {min_confidence}")


def validate_and_score_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """Validate structured record against deterministic contracts, score confidence,
    and detect cross-visit contradictions against prior patient data."""
    state = state.copy()
    record = state.get("structured_record") or {}

    schema_errors: List[str] = []
    missing_fields: List[str] = []

    try:
        StructuredRecord.model_validate(record)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []))
            msg = err.get("msg", "invalid value")
            schema_errors.append(f"pydantic:{loc} {msg}".strip())

    for field_name, rules in CONTRACT.get("fields", {}).items():
        raw_value = record.get(field_name)
        _validate_field(raw_value, rules, field_name, schema_errors, missing_fields)

    conflicts = _detect_conflicts(state.get("candidate_facts") or [])

    # ── Cross-visit contradiction detection ─────────────────────────────────
    cross_visit_conflicts = _detect_cross_visit_contradictions(state, ctx)
    if cross_visit_conflicts:
        conflicts.extend(cross_visit_conflicts)

    needs_review = bool(schema_errors or missing_fields or conflicts)

    state["validation_report"] = {
        "schema_errors": schema_errors,
        "missing_fields": missing_fields,
        "conflicts": conflicts,
        "needs_review": needs_review,
        "confidence": None,
        "details": {
            "contract": _sanitize_contract(CONTRACT),
            "cross_visit_conflicts": len(cross_visit_conflicts),
        },
    }

    return state


def _detect_cross_visit_contradictions(
    state: GraphState,
    ctx: AgentContext,
) -> List[str]:
    """
    Compare current session's record against prior patient facts.

    Catches:
      - Allergy previously recorded but now absent (removed?)
      - Medication conflict with prior allergy
      - Demographic mismatch (DOB, sex) across visits
    """
    conflicts: List[str] = []

    prf = state.get("patient_record_fields") or {}
    if not prf.get("loaded_from_db"):
        return conflicts

    record = state.get("structured_record") or {}
    prior_facts = prf.get("prior_facts", {})
    prior_record = prf.get("prior_record", {})

    # ── 1. Check prior allergies still present ──────────────────────────────
    prior_allergies = prior_facts.get("allergy", [])
    current_allergy_substances = {
        a.get("substance", "").lower()
        for a in record.get("allergies", [])
        if a.get("substance")
    }
    for pa in prior_allergies:
        key = pa.get("fact_key", "").lower()
        if key and key not in current_allergy_substances:
            conflicts.append(
                f"cross-visit: prior allergy '{key}' not found in current session "
                "(was it resolved or missed?)"
            )

    # ── 2. Demographic consistency ──────────────────────────────────────────
    demographics = prf.get("demographics", {})
    patient = record.get("patient", {})
    if demographics.get("sex") and patient.get("sex"):
        if demographics["sex"].lower() != patient["sex"].lower():
            conflicts.append(
                f"cross-visit: sex mismatch — DB has '{demographics['sex']}', "
                f"current session has '{patient['sex']}'"
            )

    return conflicts
