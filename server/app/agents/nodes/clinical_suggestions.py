"""
Agent G -- Clinical Safety Checker (Lane B ``safety_and_validate``).

Purpose: Detect allergy conflicts, drug interactions, contraindications, dosing
         problems, and out-of-range metrics.
Inputs:  structured_record, patient_id, diagnostic_reasoning (optional)
Outputs: clinical_suggestions, enriched with ``safety_tools`` results
Tools:   the three registry safety tools -- check_med_conflicts, check_dosage,
         check_metric_alerts -- called as caller="lane_b_stage",
         caller_ref="safety_and_validate" (#51). This is Lane B's registry call
         site: one contract, one receipt per call, one span per call.
Guardrail: Never suppress a critical alert.

Replaces the ToolUniverseService enrichment retired in #51. Where that service
returned one merged blob with no receipts, the registry runs the three tools in
one parallel group and each call carries its own receipt, citations rule, and
``not_covered[]``.

Supports two call signatures via ``make_node()``:
    clinical_suggestions_node(state)           -- legacy (self-wires deps)
    clinical_suggestions_node(state, ctx)      -- preferred (injected deps)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..state import GraphState

if TYPE_CHECKING:
    from ..config import AgentContext

logger = logging.getLogger(__name__)

# Shared risk ladder; the safety tools use the same order.
_RISK_ORDER = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}


def clinical_suggestions_node(
    state: GraphState,
    ctx: Optional[AgentContext] = None,
) -> GraphState:
    """
    Generate clinical suggestions based on structured record and patient history.

    When ``ctx`` is provided (via ``make_node``), uses injected services.
    Falls back to direct imports when running without AgentContext for
    backward compatibility with ``langgraph_runner.py``.

    The three safety tools run through the shared registry and their alerts
    are merged into the suggestions output. A tool that covers nothing reports
    ``not_covered`` rather than silently contributing no alerts.
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

        # -- Registry safety tools (Lane B call site, #51) ------------------
        tool_results = _run_safety_tools(
            ctx, state, structured_record, patient_history, diagnostic_reasoning, trace,
        )
        if tool_results:
            suggestions["safety_tools"] = tool_results
            if tool_results.get("metric_alerts"):
                suggestions.setdefault("lab_critical_values", [
                    alert for alert in tool_results["metric_alerts"]
                    if alert.get("severity") == "critical"
                ])
            if tool_results.get("dosage_alerts"):
                suggestions.setdefault("dosage_alerts", tool_results["dosage_alerts"])
            if tool_results.get("not_covered"):
                # Uncovered items are a safety signal, not noise: a rule table
                # that says nothing is not the same as a clean check.
                suggestions.setdefault("not_covered", tool_results["not_covered"])
            tool_risk = tool_results.get("overall_risk_level", "low")
            if tool_risk in ("critical", "high"):
                current_risk = suggestions.get("risk_level", "low")
                if _RISK_ORDER.get(tool_risk, 0) > _RISK_ORDER.get(current_risk, 0):
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
            "safety_tools_used": bool(tool_results),
            "safety_tools_run": (tool_results or {}).get("tools_executed", []),
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


def _run_safety_tools(
    ctx: Optional[Any],
    state: Dict[str, Any],
    record: Dict[str, Any],
    patient_history: Dict[str, Any],
    diagnostic_reasoning: Dict[str, Any],
    trace: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Run the three safety tools through the shared registry, in one group.

    Returns None when the registry cannot be built (no session id, import
    failure); the node then reports engine-only suggestions rather than failing
    the compile.
    """
    from ..tools import ToolRequest, ToolScope, build_registry, run_parallel_group

    session_id = state.get("session_id") or f"compile:{state.get('patient_id')}"
    try:
        scope = ToolScope(
            session_id=session_id,
            patient_id=state.get("patient_id"),
            tenant_id=state.get("tenant_id"),
        )
        registry = build_registry(scope, ctx, with_stubs=False)
    except Exception:
        logger.exception("[ClinicalSuggestions] could not build the tool registry")
        return None

    medications = _rows(record, "medications")
    allergies = _rows(record, "allergies") or _rows(patient_history, "allergies")
    problems = _problems(record, diagnostic_reasoning)
    labs = _rows(record, "labs")
    patient_params = _patient_params(record, patient_history)

    requests = [
        ToolRequest(
            tool_id="check_med_conflicts",
            args={"medications": medications, "allergies": allergies, "problems": problems},
            caller="lane_b_stage",
            caller_ref="safety_and_validate",
        ),
        ToolRequest(
            tool_id="check_dosage",
            args={"medications": medications, "patient_params": patient_params},
            caller="lane_b_stage",
            caller_ref="safety_and_validate",
        ),
        ToolRequest(
            tool_id="check_metric_alerts",
            args={"labs": labs, "patient_context": patient_params},
            caller="lane_b_stage",
            caller_ref="safety_and_validate",
        ),
    ]
    results = run_parallel_group(registry, requests, trace_log=trace)

    merged: Dict[str, Any] = {
        "tools_executed": [],
        "med_conflict_alerts": [],
        "dosage_alerts": [],
        "metric_alerts": [],
        "not_covered": [],
        "errors": {},
    }
    alert_key = {
        "check_med_conflicts": "med_conflict_alerts",
        "check_dosage": "dosage_alerts",
        "check_metric_alerts": "metric_alerts",
    }
    risks = []
    for result in results:
        tool_id = result["tool_id"]
        data = result.get("data") or {}
        merged["tools_executed"].append(tool_id)
        merged[alert_key[tool_id]] = data.get("alerts", [])
        for item in data.get("not_covered", []):
            merged["not_covered"].append({**item, "tool_id": tool_id})
        if not result["ok"]:
            merged["errors"][tool_id] = result.get("error")
        risks.append(data.get("risk_level", "low"))

    merged["overall_risk_level"] = max(
        risks or ["low"], key=lambda level: _RISK_ORDER.get(str(level), 0)
    )
    return merged


def _rows(source: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Return a list-of-objects field, ignoring anything malformed."""
    value = source.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _problems(
    record: Dict[str, Any],
    diagnostic_reasoning: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Active problems from the record, past history, and diagnostic reasoning."""
    problems: List[Dict[str, Any]] = []
    seen = set()

    def add(description: Any) -> None:
        text = str(description or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            problems.append({"description": text, "status": "active"})

    for diagnosis in _rows(record, "diagnoses"):
        add(diagnosis.get("description") or diagnosis.get("name"))
    pmh = record.get("past_medical_history")
    if isinstance(pmh, dict):
        for condition in pmh.get("chronic_conditions") or []:
            if isinstance(condition, dict):
                add(condition.get("name"))
    for diagnosis in diagnostic_reasoning.get("top_diagnoses") or []:
        if isinstance(diagnosis, dict):
            add(diagnosis.get("name"))
    return problems


def _patient_params(
    record: Dict[str, Any],
    patient_history: Dict[str, Any],
) -> Dict[str, Any]:
    """Age, sex, weight, and renal inputs the dosage and metric tools need."""
    params: Dict[str, Any] = {}
    demographics = record.get("demographics")
    if not isinstance(demographics, dict):
        demographics = patient_history.get("demographics") or {}
    age = demographics.get("age")
    if age is not None:
        try:
            params["age"] = int(age)
        except (TypeError, ValueError):
            logger.debug("[ClinicalSuggestions] non-numeric age in demographics; omitted")
    if demographics.get("sex"):
        params["sex"] = demographics["sex"]
    vitals = record.get("vitals")
    if isinstance(vitals, dict):
        for source_key, target_key in (("weight", "weight_kg"), ("height", "height_cm")):
            value = vitals.get(source_key)
            if value is not None:
                try:
                    params[target_key] = float(value)
                except (TypeError, ValueError):
                    logger.debug(
                        "[ClinicalSuggestions] non-numeric %s in vitals; omitted", source_key
                    )
    for lab in _rows(record, "labs"):
        name = str(lab.get("test_name") or lab.get("test") or "").lower()
        if name in ("creatinine", "serum creatinine"):
            try:
                params["serum_creatinine"] = float(lab.get("value"))
            except (TypeError, ValueError):
                pass
        elif name == "egfr":
            try:
                params.setdefault("labs", {})["egfr"] = float(lab.get("value"))
            except (TypeError, ValueError):
                pass
    return params
