"""
Safety tools — rule-backed, LLM-free (agent refactor Phase 1A, #51).

Plan §18.2 splits contract 1.1's `safety_check` into three tools, each wrapping
an existing engine unchanged:

    check_med_conflicts -> ClinicalSuggestionEngine (allergy cross-reactivity,
                           interactions, contraindications)
    check_dosage        -> DosageCalculator
    check_metric_alerts -> LabInterpreter reference ranges

Every result carries `not_covered[]`: the medications, parameters, or analytes
the current tables say nothing about. Silence from a rule table is not safety,
so an uncovered item is reported, never dropped. When nothing in the request is
covered at all, the tool returns `ok=False` with the contract's
`not_covered` error.

These tools are not planner-allowlisted (§18.2). A plan reaches them only
through the `safety` workflow. The versioned rule contract is #60; this issue
keeps the engines exactly as they are.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..tool_contracts import NOT_COVERED_ERROR
from .registry import ToolCall, ToolOutcome, ToolRegistry

logger = logging.getLogger(__name__)

TOOL_VERSION = "engines-1.2.0"

RISK_ORDER = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}

# Lab severities that become alerts. "borderline" and "normal" are not alerts.
ALERTING_LAB_SEVERITIES = ("critical", "high")


# ---------------------------------------------------------------------------
# check_med_conflicts
# ---------------------------------------------------------------------------


def make_med_conflicts_handler(ctx: Optional[Any] = None, engine: Optional[Any] = None):
    """Allergy conflicts, interactions, and contraindications for the given meds."""

    def handler(call: ToolCall) -> ToolOutcome:
        medications = _as_dict_list(call.args.get("medications"), "medications")
        allergies = _as_dict_list(call.args.get("allergies"), "allergies")
        problems = _as_dict_list(call.args.get("problems"), "problems")
        if not medications:
            return ToolOutcome(
                ok=True,
                data={"alerts": [], "not_covered": [], "risk_level": "low",
                      "reason": "no medications supplied"},
            )

        active_engine = _resolve(ctx, engine, "clinical_engine",
                                 "app.core.clinical_suggestions", "get_clinical_suggestion_engine")
        if active_engine is None:
            return _engine_unavailable("check_med_conflicts", medications, "medication")

        covered, not_covered = _split_medication_coverage(active_engine, medications)
        if not covered:
            return _nothing_covered(not_covered)

        record = {
            "medications": covered,
            "diagnoses": problems,
            "allergies": allergies,
        }
        history = {
            "found": True,
            "allergies": allergies,
            "medications": [],
            "diagnoses": problems,
            "labs": [],
        }
        suggestions = active_engine.generate_suggestions(
            current_record=record, patient_history=history,
        )

        alerts: List[Dict[str, Any]] = []
        for kind, key in (
            ("allergy", "allergy_alerts"),
            ("interaction", "drug_interactions"),
            ("contraindication", "contraindications"),
        ):
            for item in suggestions.get(key) or []:
                alerts.append(_alert(kind, item))

        risk_level = suggestions.get("risk_level") or _max_risk(alerts)
        logger.info(
            "check_med_conflicts: meds=%d covered=%d alerts=%d risk=%s",
            len(medications), len(covered), len(alerts), risk_level,
        )
        return ToolOutcome(
            ok=True,
            data={"alerts": alerts, "not_covered": not_covered, "risk_level": risk_level},
        )

    return handler


# ---------------------------------------------------------------------------
# check_dosage
# ---------------------------------------------------------------------------


def make_dosage_handler(ctx: Optional[Any] = None, calculator: Optional[Any] = None):
    """Dose appropriateness against age, weight, and renal parameters."""

    def handler(call: ToolCall) -> ToolOutcome:
        medications = _as_dict_list(call.args.get("medications"), "medications")
        patient_params = call.args.get("patient_params") or {}
        if not isinstance(patient_params, dict):
            raise ValueError(
                f"patient_params must be an object, got {type(patient_params).__name__}"
            )
        if not medications:
            return ToolOutcome(
                ok=True,
                data={"alerts": [], "not_covered": [], "risk_level": "low",
                      "reason": "no medications supplied"},
            )

        calc = _resolve(ctx, calculator, "dosage_calculator",
                        "app.core.dosage_calculator", "get_dosage_calculator")
        if calc is None:
            return _engine_unavailable("check_dosage", medications, "medication")

        alerts: List[Dict[str, Any]] = []
        not_covered: List[Dict[str, Any]] = []
        checked = 0

        for medication in medications:
            name = str(medication.get("name") or "").strip()
            if not name:
                not_covered.append({"medication": None, "reason": "medication has no name"})
                continue
            if not medication.get("dose"):
                not_covered.append({"medication": name, "reason": "no dose recorded"})
                continue
            if not patient_params:
                not_covered.append({
                    "medication": name,
                    "reason": "no age, weight, or renal parameters supplied",
                })
                continue
            try:
                outcome = calc.check_dosage_appropriateness(medication, patient_params)
            except Exception:
                logger.exception("check_dosage: calculator failed for a medication")
                not_covered.append({"medication": name, "reason": "dosage check failed"})
                continue

            checked += 1
            issues = outcome.get("issues") or []
            if not issues and not outcome.get("appropriate", True):
                not_covered.append({"medication": name, "reason": "no dosing table entry"})
            for issue in issues:
                alerts.append(_alert("dosage", issue, medication=name))

        if checked == 0:
            return _nothing_covered(not_covered)

        risk_level = _max_risk(alerts)
        logger.info(
            "check_dosage: meds=%d checked=%d alerts=%d not_covered=%d risk=%s",
            len(medications), checked, len(alerts), len(not_covered), risk_level,
        )
        return ToolOutcome(
            ok=True,
            data={"alerts": alerts, "not_covered": not_covered, "risk_level": risk_level},
        )

    return handler


# ---------------------------------------------------------------------------
# check_metric_alerts
# ---------------------------------------------------------------------------


def make_metric_alerts_handler(ctx: Optional[Any] = None, interpreter: Optional[Any] = None):
    """Reference-range alerts for timestamped labs and vitals."""

    def handler(call: ToolCall) -> ToolOutcome:
        metrics = _as_dict_list(
            call.args.get("labs") or call.args.get("metrics"), "labs",
        )
        patient_context = call.args.get("patient_context") or {}
        if not isinstance(patient_context, dict):
            raise ValueError(
                f"patient_context must be an object, got {type(patient_context).__name__}"
            )
        if not metrics:
            return ToolOutcome(
                ok=True,
                data={"alerts": [], "not_covered": [], "risk_level": "low",
                      "reason": "no metrics supplied"},
            )

        lab_interpreter = _resolve(ctx, interpreter, "lab_interpreter",
                                   "app.core.lab_interpreter", "get_lab_interpreter")
        if lab_interpreter is None:
            return _engine_unavailable("check_metric_alerts", metrics, "test_name")

        normalized = [
            {
                "test_name": metric.get("test_name") or metric.get("test") or metric.get("name") or "",
                "value": metric.get("value"),
                "unit": metric.get("unit", ""),
                "observed_at": metric.get("observed_at"),
            }
            for metric in metrics
        ]
        report = lab_interpreter.interpret(labs=normalized, patient_context=patient_context)
        # NB: the engine returns "interpretations"; the retired tool_universe
        # service read "results" and silently saw none.
        interpretations = report.get("interpretations") or []

        alerts: List[Dict[str, Any]] = []
        not_covered: List[Dict[str, Any]] = []
        covered = 0

        for interpretation in interpretations:
            test_name = interpretation.get("test_name")
            if interpretation.get("reference_range") is None:
                not_covered.append({
                    "test_name": test_name,
                    "reason": "no reference range in the table",
                })
                continue
            covered += 1
            if interpretation.get("severity") in ALERTING_LAB_SEVERITIES:
                alerts.append(_alert("metric", interpretation, test_name=test_name))

        skipped = len(normalized) - len(interpretations)
        if skipped > 0:
            not_covered.append({
                "test_name": None,
                "reason": f"{skipped} metric(s) had no test name or value",
            })

        if covered == 0:
            return _nothing_covered(not_covered)

        risk_level = _max_risk(alerts)
        logger.info(
            "check_metric_alerts: metrics=%d covered=%d alerts=%d not_covered=%d risk=%s",
            len(normalized), covered, len(alerts), len(not_covered), risk_level,
        )
        return ToolOutcome(
            ok=True,
            data={"alerts": alerts, "not_covered": not_covered, "risk_level": risk_level},
        )

    return handler


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_safety_tools(
    registry: ToolRegistry,
    ctx: Optional[Any] = None,
    *,
    engine: Optional[Any] = None,
    calculator: Optional[Any] = None,
    interpreter: Optional[Any] = None,
    replace: bool = True,
) -> None:
    """Register the three real safety tools, replacing any stubs."""
    registry.register(
        "check_med_conflicts", make_med_conflicts_handler(ctx, engine),
        version=TOOL_VERSION, stub=False, replace=replace,
    )
    registry.register(
        "check_dosage", make_dosage_handler(ctx, calculator),
        version=TOOL_VERSION, stub=False, replace=replace,
    )
    registry.register(
        "check_metric_alerts", make_metric_alerts_handler(ctx, interpreter),
        version=TOOL_VERSION, stub=False, replace=replace,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict_list(value: Any, field: str) -> List[Dict[str, Any]]:
    """Validate a list-of-objects argument; empty list for None."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of objects, got {type(value).__name__}")
    rows = [item for item in value if isinstance(item, dict)]
    if len(rows) != len(value):
        raise ValueError(f"{field} must contain objects only")
    return rows


def _resolve(
    ctx: Optional[Any],
    explicit: Optional[Any],
    ctx_attr: str,
    module: str,
    factory: str,
) -> Optional[Any]:
    """Prefer an injected engine, then the AgentContext, then the module factory."""
    if explicit is not None:
        return explicit
    from_ctx = getattr(ctx, ctx_attr, None) if ctx is not None else None
    if from_ctx is not None:
        return from_ctx
    try:
        imported = __import__(module, fromlist=[factory])
        return getattr(imported, factory)()
    except Exception:
        logger.exception("safety tools: could not load %s.%s", module, factory)
        return None


def _split_medication_coverage(
    engine: Any,
    medications: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split medications into ones the engine's tables know and ones they do not."""
    aliases = {
        key.lower()
        for key in list(getattr(engine, "DRUG_CLASS_ALIASES", {}))
        + list(getattr(engine, "DRUG_EXTRA_CLASSES", {}))
        + list(getattr(engine, "MEDICATION_ALLERGY_MAP", {}))
    }
    covered: List[Dict[str, Any]] = []
    not_covered: List[Dict[str, Any]] = []
    for medication in medications:
        name = str(medication.get("name") or "").strip()
        if not name:
            not_covered.append({"medication": None, "reason": "medication has no name"})
            continue
        if not aliases:
            # No table to check against: treat every medication as covered and
            # let the engine speak, rather than claiming false coverage.
            covered.append(medication)
            continue
        lowered = name.lower()
        if any(lowered == alias or alias in lowered for alias in aliases):
            covered.append(medication)
        else:
            not_covered.append({"medication": name, "reason": "not in the interaction table"})
    return covered, not_covered


def _alert(kind: str, item: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    """Normalize an engine finding into one alert shape across the three tools."""
    alert = {
        "type": item.get("type") or kind,
        "severity": item.get("severity") or item.get("risk_level") or "moderate",
        "message": (
            item.get("message")
            or item.get("interpretation")
            or item.get("description")
            or ""
        ),
        "recommendation": item.get("recommendation"),
        "source": kind,
    }
    alert.update({key: value for key, value in extra.items() if value is not None})
    for key in ("medication", "medications", "test_name", "value", "unit", "substance"):
        if key not in alert and item.get(key) is not None:
            alert[key] = item[key]
    return alert


def _max_risk(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return "low"
    return max(
        (str(alert.get("severity", "low")) for alert in alerts),
        key=lambda severity: RISK_ORDER.get(severity, 0),
    )


def _nothing_covered(not_covered: List[Dict[str, Any]]) -> ToolOutcome:
    """Contract `not_covered`: the rules say nothing about anything requested."""
    logger.info("safety tool covered nothing: items=%d", len(not_covered))
    return ToolOutcome(
        ok=False,
        data={"alerts": [], "not_covered": not_covered, "risk_level": "unknown"},
        error=NOT_COVERED_ERROR,
    )


def _engine_unavailable(tool_id: str, items: List[Dict[str, Any]], label: str) -> ToolOutcome:
    """The engine could not be loaded: report every item as uncovered, loudly."""
    logger.warning("%s: engine unavailable; reporting %d item(s) as not covered", tool_id, len(items))
    return _nothing_covered([
        {label: item.get("name") or item.get("test_name"), "reason": "engine unavailable"}
        for item in items
    ])


__all__ = [
    "ALERTING_LAB_SEVERITIES",
    "RISK_ORDER",
    "TOOL_VERSION",
    "make_dosage_handler",
    "make_med_conflicts_handler",
    "make_metric_alerts_handler",
    "register_safety_tools",
]
