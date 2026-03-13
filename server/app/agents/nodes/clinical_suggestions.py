"""
Agent G — Clinical Safety Checker.

Purpose: Detect allergy conflicts, drug interactions, contraindications.
Inputs:  structured_record, patient_id
Outputs: clinical_suggestions
Tools:   patient_lookup (via AgentContext), clinical_engine (via AgentContext)
Guardrail: Never suppress a critical alert.

Supports two call signatures via ``make_node()``:
    clinical_suggestions_node(state)           — legacy (self-wires deps)
    clinical_suggestions_node(state, ctx)      — preferred (injected deps)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..state import GraphState

if TYPE_CHECKING:
    from ..config import AgentContext


def clinical_suggestions_node(
    state: GraphState,
    ctx: Optional[AgentContext] = None,
) -> GraphState:
    """
    Generate clinical suggestions based on structured record and patient history.

    When ``ctx`` is provided (via ``make_node``), uses injected services.
    Falls back to direct imports when running without AgentContext for
    backward compatibility with ``langgraph_runner.py``.
    """
    state = {**state}  # shallow copy to avoid mutating upstream

    patient_id = state.get("patient_id")
    structured_record = state.get("structured_record", {})
    trace = state.setdefault("controls", {}).setdefault("trace_log", [])

    trace.append({
        "node": "clinical_suggestions",
        "action": "started",
        "timestamp": datetime.now().isoformat(),
    })

    # ── Guard: required inputs ──────────────────────────────────────────────
    if not patient_id:
        trace.append({
            "node": "clinical_suggestions",
            "action": "skipped",
            "reason": "No patient_id provided",
            "timestamp": datetime.now().isoformat(),
        })
        return state

    if not structured_record:
        trace.append({
            "node": "clinical_suggestions",
            "action": "skipped",
            "reason": "No structured_record available",
            "timestamp": datetime.now().isoformat(),
        })
        return state

    try:
        # ── Resolve services (prefer context, fallback to legacy) ───────────
        patient_history = _get_patient_history(patient_id, ctx)

        if not patient_history or not patient_history.get("found"):
            trace.append({
                "node": "clinical_suggestions",
                "action": "skipped",
                "reason": "Patient history not found",
                "timestamp": datetime.now().isoformat(),
            })
            return state

        engine = _get_engine(ctx)
        suggestions = engine.generate_suggestions(
            current_record=structured_record,
            patient_history=patient_history,
        )

        state["clinical_suggestions"] = suggestions

        # Guardrail: critical alerts MUST flag for human review
        if suggestions.get("risk_level") == "critical":
            flags = state.setdefault("flags", {})
            flags["needs_review"] = True
            review_reasons = flags.setdefault("review_reasons", [])
            review_reasons.append(
                f"Critical clinical alert: "
                f"{len(suggestions.get('allergy_alerts', []))} allergy alert(s)"
            )

        trace.append({
            "node": "clinical_suggestions",
            "action": "completed",
            "risk_level": suggestions.get("risk_level"),
            "allergy_alerts": len(suggestions.get("allergy_alerts", [])),
            "drug_interactions": len(suggestions.get("drug_interactions", [])),
            "contraindications": len(suggestions.get("contraindications", [])),
            "timestamp": datetime.now().isoformat(),
        })

    except Exception as e:
        trace.append({
            "node": "clinical_suggestions",
            "action": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })
        # Fail open — empty suggestions, don't block the pipeline
        state["clinical_suggestions"] = {
            "allergy_alerts": [],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "unknown",
            "error": str(e),
        }

    return state


# ── Private helpers ─────────────────────────────────────────────────────────

def _get_patient_history(
    patient_id: str,
    ctx: Optional[AgentContext],
) -> Optional[Dict[str, Any]]:
    """Resolve patient history from context or legacy imports."""
    if ctx and ctx.patient_service:
        return ctx.patient_service.get_patient_history(patient_id)

    # Legacy fallback: wire deps ourselves
    try:
        from app.database.session import get_db_context
        from app.core.patient_service import get_patient_service

        with get_db_context() as db:
            svc = get_patient_service(db)
            return svc.get_patient_history(patient_id)
    except Exception:
        return None


def _get_engine(ctx: Optional[AgentContext]):
    """Resolve the clinical suggestion engine."""
    if ctx and ctx.clinical_engine:
        return ctx.clinical_engine

    from app.core.clinical_suggestions import get_clinical_suggestion_engine
    return get_clinical_suggestion_engine()
