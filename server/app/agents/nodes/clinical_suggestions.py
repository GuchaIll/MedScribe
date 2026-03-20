"""
Agent G -- Clinical Safety Checker (with ToolUniverse integration).

Purpose: Detect allergy conflicts, drug interactions, contraindications.
         Enhanced with ToolUniverse for lab interpretation, dosage checks,
         and comprehensive tool-backed validation.
Inputs:  structured_record, patient_id, diagnostic_reasoning (optional)
Outputs: clinical_suggestions (enriched with tool results)
Tools:   patient_lookup (via AgentContext), clinical_engine (via AgentContext),
         ToolUniverseService (via AgentContext)
Guardrail: Never suppress a critical alert.

Supports two call signatures via ``make_node()``:
    clinical_suggestions_node(state)           -- legacy (self-wires deps)
    clinical_suggestions_node(state, ctx)      -- preferred (injected deps)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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

    Enhancement: when ToolUniverseService is available via ctx, runs
    additional tool-backed checks (lab interpretation, dosage validation)
    and merges results into the suggestions output.
    """
    state = {**state}  # shallow copy to avoid mutating upstream

    patient_id = state.get("patient_id")
    structured_record = state.get("structured_record", {})
    diagnostic_reasoning = state.get("diagnostic_reasoning") or {}
    trace = state.setdefault("controls", {}).setdefault("trace_log", [])

    trace.append({
        "node": "clinical_suggestions",
        "action": "started",
        "timestamp": datetime.now().isoformat(),
    })

    # -- Guard: required inputs -------------------------------------------
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
        # -- Resolve services (prefer context, fallback to legacy) ---------
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

        # -- ToolUniverse enrichment ---------------------------------------
        tool_results = _run_tool_universe_checks(
            ctx, structured_record, patient_history, diagnostic_reasoning,
        )
        if tool_results:
            suggestions["tool_universe"] = tool_results
            # Merge critical lab values into risk consideration
            if tool_results.get("lab_interpretation", {}).get("critical_values"):
                suggestions.setdefault("lab_critical_values",
                                       tool_results["lab_interpretation"]["critical_values"])
            # Merge dosage alerts
            if tool_results.get("dosage_check", {}).get("dosage_alerts"):
                suggestions.setdefault("dosage_alerts",
                                       tool_results["dosage_check"]["dosage_alerts"])
            # Escalate risk if tools found critical issues
            tool_risk = tool_results.get("overall_risk_level", "low")
            if tool_risk in ("critical", "high"):
                current_risk = suggestions.get("risk_level", "low")
                risk_order = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}
                if risk_order.get(tool_risk, 0) > risk_order.get(current_risk, 0):
                    suggestions["risk_level"] = tool_risk

        # -- Integrate diagnostic reasoning risk flags ---------------------
        if diagnostic_reasoning.get("risk_flags"):
            existing_flags = suggestions.get("risk_flags", [])
            for rf in diagnostic_reasoning["risk_flags"]:
                existing_flags.append({
                    "flag": rf.get("flag", ""),
                    "severity": rf.get("severity", "moderate"),
                    "source": "diagnostic_reasoning",
                })
            suggestions["risk_flags"] = existing_flags

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
            "tool_universe_used": bool(tool_results),
            "timestamp": datetime.now().isoformat(),
        })

    except Exception as e:
        trace.append({
            "node": "clinical_suggestions",
            "action": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })
        # Fail open -- empty suggestions, don't block the pipeline
        state["clinical_suggestions"] = {
            "allergy_alerts": [],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "unknown",
            "error": str(e),
        }

    return state


# -- Private helpers ----------------------------------------------------------

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


def _run_tool_universe_checks(
    ctx: Optional[Any],
    record: Dict[str, Any],
    patient_history: Dict[str, Any],
    diagnostic_reasoning: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Run ToolUniverse tool-backed checks if the service is available.

    Returns None when ToolUniverseService is not wired up.
    """
    tool_svc = None
    if ctx and hasattr(ctx, "tool_universe_service") and ctx.tool_universe_service:
        tool_svc = ctx.tool_universe_service
    else:
        # Try lazy import
        try:
            from app.agents.tools.tool_universe import get_tool_universe_service
            tool_svc = get_tool_universe_service()
        except Exception:
            return None

    if tool_svc is None:
        return None

    # Build patient params from record
    demo = record.get("demographics") or {}
    vitals = record.get("vitals") or {}
    patient_params: Dict[str, Any] = {}
    if demo.get("age"):
        try:
            patient_params["age"] = int(demo["age"])
        except (ValueError, TypeError):
            pass
    if demo.get("sex"):
        patient_params["sex"] = demo["sex"]
    if isinstance(vitals, dict):
        if vitals.get("weight"):
            patient_params["weight_kg"] = vitals["weight"]

    # Gather conditions list from diagnoses + chronic conditions
    conditions: List[str] = []
    for dx in record.get("diagnoses", []):
        desc = dx.get("description") or dx.get("name", "")
        if desc:
            conditions.append(desc)
    pmh = record.get("past_medical_history") or {}
    for cc in pmh.get("chronic_conditions", []):
        name = cc.get("name", "")
        if name and name not in conditions:
            conditions.append(name)

    # Add conditions from diagnostic reasoning
    for dx in diagnostic_reasoning.get("top_diagnoses", []):
        dx_name = dx.get("name", "")
        if dx_name and dx_name not in conditions:
            conditions.append(dx_name)

    try:
        return tool_svc.query_comprehensive(
            medications=record.get("medications", []),
            allergies=record.get("allergies") or patient_history.get("allergies", []),
            labs=record.get("labs", []),
            conditions=conditions,
            patient_params=patient_params if patient_params else None,
            patient_history=patient_history,
        )
    except Exception:
        return None
