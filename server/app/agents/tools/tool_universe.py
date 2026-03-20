"""
ToolUniverse Service -- Unified medical knowledge tool interface.

Wraps existing clinical tools (ClinicalSuggestionEngine, DosageCalculator,
LabInterpreter, DrugCheckerTool) into a single service that can be queried
by the clinical_suggestions node and diagnostic_reasoning node.

Mirrors the ToolUniverse agent YAML schema:
    - medical_drugs:       drug interactions, contraindications, prescribing guidance
    - medical_diagnostics: diagnostic criteria, recommended workup
    - lab_interpretation:  reference ranges, critical values, clinical significance
    - dosage_calculation:  weight/renal/age-based dose adjustments
    - medical_symptoms:    symptom-disease associations (rule-based)

All tool calls are local and synchronous (no external API by default).
External APIs (RxNorm, OpenFDA) are used only when the underlying engine
has ``use_external_database=True``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolUniverseService:
    """
    Unified interface to all local medical knowledge tools.

    Instantiate once and inject via AgentContext. Each ``query_*`` method
    returns a structured result dict that can be merged into diagnostic
    reasoning or clinical suggestions.
    """

    def __init__(
        self,
        clinical_engine: Optional[Any] = None,
        dosage_calculator: Optional[Any] = None,
        lab_interpreter: Optional[Any] = None,
        drug_checker: Optional[Any] = None,
    ):
        self._clinical_engine = clinical_engine
        self._dosage_calculator = dosage_calculator
        self._lab_interpreter = lab_interpreter
        self._drug_checker = drug_checker

    # -- Lazy loaders -------------------------------------------------------

    @property
    def clinical_engine(self):
        if self._clinical_engine is None:
            try:
                from app.core.clinical_suggestions import get_clinical_suggestion_engine
                self._clinical_engine = get_clinical_suggestion_engine()
            except Exception as exc:
                logger.warning("Failed to load clinical suggestion engine: %s", exc)
        return self._clinical_engine

    @property
    def dosage_calculator(self):
        if self._dosage_calculator is None:
            try:
                from app.core.dosage_calculator import get_dosage_calculator
                self._dosage_calculator = get_dosage_calculator()
            except Exception as exc:
                logger.warning("Failed to load dosage calculator: %s", exc)
        return self._dosage_calculator

    @property
    def lab_interpreter(self):
        if self._lab_interpreter is None:
            try:
                from app.core.lab_interpreter import get_lab_interpreter
                self._lab_interpreter = get_lab_interpreter()
            except Exception as exc:
                logger.warning("Failed to load lab interpreter: %s", exc)
        return self._lab_interpreter

    @property
    def drug_checker(self):
        if self._drug_checker is None:
            try:
                from app.agents.tools.drug_checker import DrugCheckerTool
                self._drug_checker = DrugCheckerTool(engine=self.clinical_engine)
            except Exception as exc:
                logger.warning("Failed to load drug checker: %s", exc)
        return self._drug_checker

    # ======================================================================
    # Public query methods (one per tool_universe category)
    # ======================================================================

    def query_drug_info(
        self,
        medications: List[Dict[str, Any]],
        allergies: Optional[List[Dict[str, Any]]] = None,
        conditions: Optional[List[str]] = None,
        patient_history: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Query drug interactions, allergy conflicts, and contraindications.

        Returns:
            Dict with keys: drug_interactions, allergy_alerts,
            contraindications, risk_level.
        """
        result: Dict[str, Any] = {
            "drug_interactions": [],
            "allergy_alerts": [],
            "contraindications": [],
            "risk_level": "low",
        }

        if not medications:
            return result

        engine = self.clinical_engine
        if engine is None:
            return result

        # Build a minimal record / history for the engine
        current_record = {
            "medications": medications,
            "diagnoses": [{"description": c} for c in (conditions or [])],
        }

        history = patient_history or {
            "found": True,
            "allergies": allergies or [],
            "medications": [],
            "diagnoses": [{"description": c, "status": "active"} for c in (conditions or [])],
            "labs": [],
        }

        try:
            suggestions = engine.generate_suggestions(
                current_record=current_record,
                patient_history=history,
            )
            result["drug_interactions"] = suggestions.get("drug_interactions", [])
            result["allergy_alerts"] = suggestions.get("allergy_alerts", [])
            result["contraindications"] = suggestions.get("contraindications", [])
            result["risk_level"] = suggestions.get("risk_level", "low")
        except Exception as exc:
            logger.warning("Drug info query failed: %s", exc)

        return result

    def query_lab_interpretation(
        self,
        labs: List[Dict[str, Any]],
        patient_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Interpret laboratory results.

        Args:
            labs: list of {test_name/test, value, unit}
            patient_context: optional {age, sex} for adjusted ranges

        Returns:
            Dict with interpretations, critical_values, abnormal_count.
        """
        result: Dict[str, Any] = {
            "interpretations": [],
            "critical_values": [],
            "abnormal_count": 0,
            "normal_count": 0,
        }

        interpreter = self.lab_interpreter
        if interpreter is None or not labs:
            return result

        # Normalize lab key names (test_name vs test)
        normalized_labs = []
        for lab in labs:
            normalized_labs.append({
                "test_name": lab.get("test_name") or lab.get("test", ""),
                "value": lab.get("value"),
                "unit": lab.get("unit", ""),
            })

        try:
            interpretation = interpreter.interpret(
                labs=normalized_labs,
                patient_context=patient_context or {},
            )
            result["interpretations"] = interpretation.get("results", [])
            result["critical_values"] = [
                r for r in result["interpretations"]
                if r.get("flag") == "critical"
            ]
            result["abnormal_count"] = sum(
                1 for r in result["interpretations"]
                if r.get("flag") in ("high", "low", "critical")
            )
            result["normal_count"] = sum(
                1 for r in result["interpretations"]
                if r.get("flag") == "normal"
            )
        except Exception as exc:
            logger.warning("Lab interpretation failed: %s", exc)

        return result

    def query_dosage_check(
        self,
        medications: List[Dict[str, Any]],
        patient_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check dosage appropriateness for given patient parameters.

        Args:
            medications: list of {name, dose, route, frequency}
            patient_params: {age, sex, weight_kg, serum_creatinine, egfr}

        Returns:
            Dict with dosage_alerts, adjustments.
        """
        result: Dict[str, Any] = {
            "dosage_alerts": [],
            "adjustments": [],
        }

        calc = self.dosage_calculator
        if calc is None or not medications:
            return result

        params = patient_params or {}
        age = params.get("age")
        weight = params.get("weight_kg")
        sex = params.get("sex", "")
        creatinine = params.get("serum_creatinine")

        for med in medications:
            med_name = (med.get("name") or "").lower().strip()
            if not med_name:
                continue

            alerts: List[Dict[str, Any]] = []

            # Renal dosing check
            if creatinine and age and weight:
                try:
                    crcl = calc.calculate_creatinine_clearance(
                        age=int(age),
                        weight_kg=float(weight),
                        serum_creatinine=float(creatinine),
                        sex=sex[0].upper() if sex else "M",
                    )
                    if hasattr(calc, "check_renal_dosing"):
                        renal_alert = calc.check_renal_dosing(med_name, crcl)
                        if renal_alert:
                            alerts.append(renal_alert)
                except Exception:
                    pass

            # Geriatric check
            if age and int(age) >= 65:
                if hasattr(calc, "check_geriatric_appropriateness"):
                    try:
                        geri_alert = calc.check_geriatric_appropriateness(med_name)
                        if geri_alert:
                            alerts.append(geri_alert)
                    except Exception:
                        pass

            if alerts:
                result["dosage_alerts"].extend(alerts)
                result["adjustments"].append({
                    "medication": med.get("name"),
                    "alerts": alerts,
                })

        return result

    def query_comprehensive(
        self,
        medications: Optional[List[Dict[str, Any]]] = None,
        allergies: Optional[List[Dict[str, Any]]] = None,
        labs: Optional[List[Dict[str, Any]]] = None,
        conditions: Optional[List[str]] = None,
        patient_params: Optional[Dict[str, Any]] = None,
        patient_history: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run all available tools and merge results.

        Returns a unified dict with keys from each sub-query.
        """
        result: Dict[str, Any] = {
            "drug_info": {},
            "lab_interpretation": {},
            "dosage_check": {},
            "tools_executed": [],
        }

        if medications:
            result["drug_info"] = self.query_drug_info(
                medications=medications,
                allergies=allergies,
                conditions=conditions,
                patient_history=patient_history,
            )
            result["tools_executed"].append("medical_drugs")

        if labs:
            result["lab_interpretation"] = self.query_lab_interpretation(
                labs=labs,
                patient_context=patient_params,
            )
            result["tools_executed"].append("lab_interpretation")

        if medications and patient_params:
            result["dosage_check"] = self.query_dosage_check(
                medications=medications,
                patient_params=patient_params,
            )
            result["tools_executed"].append("dosage_calculation")

        # Aggregate risk level
        risk_levels = []
        drug_risk = result["drug_info"].get("risk_level", "low")
        if drug_risk:
            risk_levels.append(drug_risk)
        if result["lab_interpretation"].get("critical_values"):
            risk_levels.append("critical")

        result["overall_risk_level"] = _max_risk(risk_levels)

        return result


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------

_instance: Optional[ToolUniverseService] = None


def get_tool_universe_service(
    clinical_engine: Optional[Any] = None,
    dosage_calculator: Optional[Any] = None,
    lab_interpreter: Optional[Any] = None,
    drug_checker: Optional[Any] = None,
) -> ToolUniverseService:
    """Return a (lazily initialized) singleton ToolUniverseService."""
    global _instance
    if _instance is None:
        _instance = ToolUniverseService(
            clinical_engine=clinical_engine,
            dosage_calculator=dosage_calculator,
            lab_interpreter=lab_interpreter,
            drug_checker=drug_checker,
        )
    return _instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RISK_ORDER = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}


def _max_risk(levels: List[str]) -> str:
    """Return the highest risk level from a list."""
    if not levels:
        return "low"
    return max(levels, key=lambda r: _RISK_ORDER.get(r, 0))
