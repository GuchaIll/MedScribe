"""
Lab Result Interpretation Service.

Interprets laboratory values against reference ranges with age/sex
adjustments, flags critical values, and provides clinical significance
context.  Optionally enriches interpretations with LLM-generated
clinical narratives when an LLM factory is available.

Usage::

    interpreter = get_lab_interpreter()
    result = interpreter.interpret(
        labs=[{"test_name": "HbA1c", "value": 7.2, "unit": "%"}],
        patient_context={"age": 65, "sex": "male"},
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Reference ranges ────────────────────────────────────────────────────────
# Each entry: (low, high, unit, critical_low, critical_high)
# None means no limit in that direction.

REFERENCE_RANGES: Dict[str, Dict[str, Any]] = {
    # Metabolic panel
    "glucose":            {"low": 70, "high": 100, "unit": "mg/dL", "crit_low": 40, "crit_high": 500},
    "fasting glucose":    {"low": 70, "high": 100, "unit": "mg/dL", "crit_low": 40, "crit_high": 500},
    "bun":                {"low": 7,  "high": 20,  "unit": "mg/dL", "crit_low": None, "crit_high": 100},
    "creatinine":         {"low": 0.6, "high": 1.2, "unit": "mg/dL", "crit_low": None, "crit_high": 10.0},
    "sodium":             {"low": 136, "high": 145, "unit": "mEq/L", "crit_low": 120, "crit_high": 160},
    "potassium":          {"low": 3.5, "high": 5.0, "unit": "mEq/L", "crit_low": 2.5, "crit_high": 6.5},
    "chloride":           {"low": 98,  "high": 106, "unit": "mEq/L", "crit_low": 80, "crit_high": 120},
    "co2":                {"low": 23,  "high": 29,  "unit": "mEq/L", "crit_low": 10, "crit_high": 40},
    "bicarbonate":        {"low": 23,  "high": 29,  "unit": "mEq/L", "crit_low": 10, "crit_high": 40},
    "calcium":            {"low": 8.5, "high": 10.5, "unit": "mg/dL", "crit_low": 6.0, "crit_high": 13.0},
    "magnesium":          {"low": 1.7, "high": 2.2, "unit": "mg/dL", "crit_low": 1.0, "crit_high": 4.0},
    "phosphorus":         {"low": 2.5, "high": 4.5, "unit": "mg/dL", "crit_low": 1.0, "crit_high": 8.0},
    "uric acid":          {"low": 3.0, "high": 7.0, "unit": "mg/dL", "crit_low": None, "crit_high": 12.0},

    # Liver panel
    "alt":                {"low": 7,   "high": 56,  "unit": "U/L", "crit_low": None, "crit_high": 1000},
    "ast":                {"low": 10,  "high": 40,  "unit": "U/L", "crit_low": None, "crit_high": 1000},
    "alp":                {"low": 44,  "high": 147, "unit": "U/L", "crit_low": None, "crit_high": None},
    "bilirubin total":    {"low": 0.1, "high": 1.2, "unit": "mg/dL", "crit_low": None, "crit_high": 15.0},
    "bilirubin direct":   {"low": 0.0, "high": 0.3, "unit": "mg/dL", "crit_low": None, "crit_high": None},
    "albumin":            {"low": 3.5, "high": 5.5, "unit": "g/dL", "crit_low": 1.5, "crit_high": None},
    "total protein":      {"low": 6.0, "high": 8.3, "unit": "g/dL", "crit_low": None, "crit_high": None},
    "ggt":                {"low": 0,   "high": 65,  "unit": "U/L", "crit_low": None, "crit_high": None},

    # Complete blood count
    "wbc":                {"low": 4.5, "high": 11.0, "unit": "K/uL", "crit_low": 2.0, "crit_high": 30.0},
    "rbc":                {"low": 4.0, "high": 5.5,  "unit": "M/uL", "crit_low": 2.0, "crit_high": 7.5},
    "hemoglobin":         {"low": 12.0, "high": 17.5, "unit": "g/dL", "crit_low": 7.0, "crit_high": 20.0},
    "hgb":                {"low": 12.0, "high": 17.5, "unit": "g/dL", "crit_low": 7.0, "crit_high": 20.0},
    "hematocrit":         {"low": 36, "high": 50,    "unit": "%", "crit_low": 20, "crit_high": 60},
    "hct":                {"low": 36, "high": 50,    "unit": "%", "crit_low": 20, "crit_high": 60},
    "platelets":          {"low": 150, "high": 400,  "unit": "K/uL", "crit_low": 50, "crit_high": 1000},
    "plt":                {"low": 150, "high": 400,  "unit": "K/uL", "crit_low": 50, "crit_high": 1000},
    "mcv":                {"low": 80, "high": 100,   "unit": "fL", "crit_low": None, "crit_high": None},
    "mch":                {"low": 27, "high": 33,    "unit": "pg", "crit_low": None, "crit_high": None},
    "mchc":               {"low": 32, "high": 36,    "unit": "g/dL", "crit_low": None, "crit_high": None},

    # Coagulation
    "pt":                 {"low": 11, "high": 13.5, "unit": "sec", "crit_low": None, "crit_high": 30},
    "inr":                {"low": 0.8, "high": 1.1, "unit": "", "crit_low": None, "crit_high": 5.0},
    "aptt":               {"low": 25, "high": 35,   "unit": "sec", "crit_low": None, "crit_high": 100},
    "ptt":                {"low": 25, "high": 35,   "unit": "sec", "crit_low": None, "crit_high": 100},

    # Lipid panel
    "total cholesterol":  {"low": 0,   "high": 200, "unit": "mg/dL", "crit_low": None, "crit_high": 400},
    "cholesterol":        {"low": 0,   "high": 200, "unit": "mg/dL", "crit_low": None, "crit_high": 400},
    "ldl":                {"low": 0,   "high": 100, "unit": "mg/dL", "crit_low": None, "crit_high": 300},
    "hdl":                {"low": 40,  "high": 999, "unit": "mg/dL", "crit_low": 20, "crit_high": None},
    "triglycerides":      {"low": 0,   "high": 150, "unit": "mg/dL", "crit_low": None, "crit_high": 500},

    # Thyroid
    "tsh":                {"low": 0.4, "high": 4.0, "unit": "mIU/L", "crit_low": 0.01, "crit_high": 50},
    "free t4":            {"low": 0.8, "high": 1.8, "unit": "ng/dL", "crit_low": 0.2, "crit_high": 5.0},
    "free t3":            {"low": 2.3, "high": 4.2, "unit": "pg/mL", "crit_low": None, "crit_high": None},

    # Diabetes / A1c
    "hba1c":              {"low": 4.0, "high": 5.6, "unit": "%", "crit_low": None, "crit_high": 14.0},
    "a1c":                {"low": 4.0, "high": 5.6, "unit": "%", "crit_low": None, "crit_high": 14.0},
    "hemoglobin a1c":     {"low": 4.0, "high": 5.6, "unit": "%", "crit_low": None, "crit_high": 14.0},

    # Renal
    "egfr":               {"low": 90, "high": 999, "unit": "mL/min/1.73m2", "crit_low": 15, "crit_high": None},
    "microalbumin":       {"low": 0,   "high": 30,  "unit": "mg/L", "crit_low": None, "crit_high": 300},

    # Cardiac
    "troponin":           {"low": 0, "high": 0.04, "unit": "ng/mL", "crit_low": None, "crit_high": 0.4},
    "troponin i":         {"low": 0, "high": 0.04, "unit": "ng/mL", "crit_low": None, "crit_high": 0.4},
    "bnp":                {"low": 0, "high": 100,  "unit": "pg/mL", "crit_low": None, "crit_high": 900},
    "nt-probnp":          {"low": 0, "high": 300,  "unit": "pg/mL", "crit_low": None, "crit_high": 1800},
    "ck":                 {"low": 30, "high": 200,  "unit": "U/L", "crit_low": None, "crit_high": 1000},
    "ck-mb":              {"low": 0, "high": 5.0,   "unit": "ng/mL", "crit_low": None, "crit_high": 25},

    # Iron
    "iron":               {"low": 60, "high": 170, "unit": "ug/dL", "crit_low": None, "crit_high": None},
    "ferritin":           {"low": 12, "high": 300, "unit": "ng/mL", "crit_low": None, "crit_high": 1000},
    "tibc":               {"low": 250, "high": 370, "unit": "ug/dL", "crit_low": None, "crit_high": None},

    # Inflammatory
    "crp":                {"low": 0, "high": 3.0, "unit": "mg/L", "crit_low": None, "crit_high": 200},
    "esr":                {"low": 0, "high": 20,  "unit": "mm/hr", "crit_low": None, "crit_high": 100},

    # Vitamins
    "vitamin d":          {"low": 30, "high": 100, "unit": "ng/mL", "crit_low": 10, "crit_high": 150},
    "vitamin b12":        {"low": 200, "high": 900, "unit": "pg/mL", "crit_low": 100, "crit_high": None},
    "folate":             {"low": 2.7, "high": 17.0, "unit": "ng/mL", "crit_low": None, "crit_high": None},

    # Urinalysis
    "ph (urine)":         {"low": 4.5, "high": 8.0, "unit": "", "crit_low": None, "crit_high": None},
    "specific gravity":   {"low": 1.005, "high": 1.030, "unit": "", "crit_low": None, "crit_high": None},

    # PSA
    "psa":                {"low": 0, "high": 4.0, "unit": "ng/mL", "crit_low": None, "crit_high": 20.0},
}


# Age/sex adjustments applied on top of base ranges
_SEX_ADJUSTMENTS: Dict[str, Dict[str, tuple]] = {
    "hemoglobin": {"male": (13.5, 17.5), "female": (12.0, 16.0)},
    "hgb":        {"male": (13.5, 17.5), "female": (12.0, 16.0)},
    "hematocrit": {"male": (38.3, 50),   "female": (35.5, 44.9)},
    "hct":        {"male": (38.3, 50),   "female": (35.5, 44.9)},
    "rbc":        {"male": (4.5, 5.9),   "female": (4.0, 5.2)},
    "creatinine": {"male": (0.7, 1.3),   "female": (0.6, 1.1)},
    "ferritin":   {"male": (20, 500),    "female": (12, 150)},
    "iron":       {"male": (65, 175),    "female": (50, 170)},
    "uric acid":  {"male": (3.4, 7.0),   "female": (2.4, 6.0)},
}


class LabInterpreter:
    """Interprets lab values against reference ranges with clinical context."""

    def interpret(
        self,
        labs: List[Dict[str, Any]],
        patient_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Interpret a list of lab results.

        Parameters
        ----------
        labs : list of dict
            Each item should have ``test_name``, ``value``, and optionally
            ``unit`` and ``reference_range``.
        patient_context : dict, optional
            ``age``, ``sex``, ``conditions`` for adjusted interpretation.

        Returns
        -------
        dict
            ``interpretations`` — per-test results,
            ``risk_flags`` — critical/urgent items,
            ``summary`` — human-readable narrative.
        """
        ctx = patient_context or {}
        age = ctx.get("age")
        sex = (ctx.get("sex") or "").lower()
        conditions = ctx.get("conditions", [])

        interpretations: List[Dict[str, Any]] = []
        risk_flags: List[str] = []

        for lab in labs:
            test_name = (lab.get("test_name") or "").strip()
            raw_value = lab.get("value")
            unit = lab.get("unit", "")

            if not test_name or raw_value is None:
                continue

            interp = self._interpret_single(
                test_name, raw_value, unit, age, sex, conditions
            )
            interpretations.append(interp)

            if interp["severity"] == "critical":
                risk_flags.append(
                    f"CRITICAL: {test_name} = {raw_value} {unit} — {interp['interpretation']}"
                )
            elif interp["severity"] == "high" and interp.get("is_abnormal"):
                risk_flags.append(
                    f"ALERT: {test_name} = {raw_value} {unit} — {interp['interpretation']}"
                )

        summary = self._build_summary(interpretations, risk_flags, ctx)

        return {
            "interpretations": interpretations,
            "risk_flags": risk_flags,
            "summary": summary,
        }

    # ── Single test interpretation ──────────────────────────────────────────

    def _interpret_single(
        self,
        test_name: str,
        raw_value: Any,
        unit: str,
        age: Optional[int],
        sex: str,
        conditions: List[Any],
    ) -> Dict[str, Any]:
        """Interpret one lab result."""
        key = test_name.lower().strip()

        # Try numeric parse
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return {
                "test_name": test_name,
                "value": str(raw_value),
                "unit": unit,
                "reference_range": None,
                "is_abnormal": False,
                "severity": "info",
                "interpretation": f"{test_name}: non-numeric value '{raw_value}'",
                "clinical_significance": "",
            }

        ref = REFERENCE_RANGES.get(key)
        if ref is None:
            return {
                "test_name": test_name,
                "value": value,
                "unit": unit,
                "reference_range": None,
                "is_abnormal": False,
                "severity": "info",
                "interpretation": f"{test_name} = {value} {unit} (no reference range available)",
                "clinical_significance": "",
            }

        # Adjust ranges by sex
        low, high = ref["low"], ref["high"]
        if sex in ("male", "female") and key in _SEX_ADJUSTMENTS:
            low, high = _SEX_ADJUSTMENTS[key][sex]

        crit_low = ref.get("crit_low")
        crit_high = ref.get("crit_high")
        ref_unit = ref.get("unit", unit)

        # Determine status
        is_abnormal = False
        severity = "normal"
        direction = ""

        if crit_low is not None and value < crit_low:
            severity, is_abnormal, direction = "critical", True, "critically low"
        elif crit_high is not None and value > crit_high:
            severity, is_abnormal, direction = "critical", True, "critically high"
        elif low is not None and value < low:
            severity, is_abnormal, direction = "high", True, "low"
        elif high is not None and value > high:
            severity, is_abnormal, direction = "high", True, "high"
        elif low is not None and value < low * 1.1:
            severity, direction = "borderline", "borderline low"
        elif high is not None and high < 900 and value > high * 0.9:
            severity, direction = "borderline", "borderline high"
        else:
            direction = "within normal limits"

        range_str = f"{low}-{high}" if low is not None and high is not None else "—"
        interpretation = f"{test_name} = {value} {ref_unit}: {direction} (ref {range_str})"

        clinical_significance = self._get_clinical_significance(
            key, value, direction, severity, age, sex, conditions
        )

        return {
            "test_name": test_name,
            "value": value,
            "unit": ref_unit,
            "reference_range": range_str,
            "is_abnormal": is_abnormal,
            "severity": severity,
            "interpretation": interpretation,
            "clinical_significance": clinical_significance,
        }

    # ── Clinical significance rules ────────────────────────────────────────

    def _get_clinical_significance(
        self,
        key: str,
        value: float,
        direction: str,
        severity: str,
        age: Optional[int],
        sex: str,
        conditions: List[Any],
    ) -> str:
        """Return clinical significance note for abnormal values."""
        if severity in ("normal", "borderline"):
            return ""

        condition_names = [
            (c.get("description") or c.get("name") or str(c)).lower()
            if isinstance(c, dict) else str(c).lower()
            for c in conditions
        ]

        notes: List[str] = []

        # Renal
        if key in ("creatinine", "bun", "egfr"):
            if key == "egfr" and value < 60:
                notes.append("Suggests chronic kidney disease (CKD stage 3+)")
            elif key == "egfr" and value < 30:
                notes.append("Severe renal impairment — review medication dosing")
            if key == "creatinine" and "high" in direction:
                notes.append("Elevated creatinine may indicate renal dysfunction")
                if any("diabetes" in c for c in condition_names):
                    notes.append("Monitor for diabetic nephropathy")

        # Diabetes
        if key in ("hba1c", "a1c", "hemoglobin a1c"):
            if value > 6.4:
                notes.append("HbA1c > 6.4%: consistent with diabetes mellitus")
            elif value > 5.6:
                notes.append("HbA1c 5.7–6.4%: prediabetes range")
        if key in ("glucose", "fasting glucose") and value > 126:
            notes.append("Fasting glucose > 126 mg/dL: consistent with diabetes")

        # Cardiac
        if key in ("troponin", "troponin i") and "high" in direction:
            notes.append("Elevated troponin: evaluate for acute coronary syndrome")
        if key in ("bnp", "nt-probnp") and "high" in direction:
            notes.append("Elevated BNP: evaluate for heart failure")

        # Liver
        if key in ("alt", "ast") and "high" in direction:
            notes.append("Elevated transaminases: evaluate for hepatic injury")
        if key == "bilirubin total" and value > 2.0:
            notes.append("Hyperbilirubinemia: evaluate for hepatobiliary disease")

        # Thyroid
        if key == "tsh":
            if "high" in direction:
                notes.append("Elevated TSH: evaluate for hypothyroidism")
            elif "low" in direction:
                notes.append("Suppressed TSH: evaluate for hyperthyroidism")

        # Electrolytes
        if key == "potassium":
            if "high" in direction:
                notes.append("Hyperkalemia: cardiac risk — review medications (ACEi, K-sparing diuretics)")
            elif "low" in direction:
                notes.append("Hypokalemia: arrhythmia risk — evaluate magnesium, diuretic use")
        if key == "sodium":
            if "low" in direction:
                notes.append("Hyponatremia: assess volume status, medications (SSRI, thiazides)")
            elif "high" in direction:
                notes.append("Hypernatremia: assess hydration status")

        # Heme
        if key in ("hemoglobin", "hgb") and "low" in direction:
            notes.append("Anemia: evaluate MCV for classification (iron, B12, folate)")
            if age and age > 65:
                notes.append("In elderly: evaluate for occult GI blood loss")
        if key in ("wbc",):
            if "high" in direction:
                notes.append("Leukocytosis: evaluate for infection, inflammation, or hematologic disorder")
            elif "low" in direction:
                notes.append("Leukopenia: evaluate for bone marrow suppression, infection risk")
        if key in ("platelets", "plt") and "low" in direction:
            notes.append("Thrombocytopenia: bleeding risk — review medications (heparin, chemo)")

        # Coag
        if key == "inr" and value > 3.0:
            notes.append("INR > 3.0: bleeding risk with warfarin — consider dose adjustment")

        # Lipids
        if key == "ldl" and value > 190:
            notes.append("Very high LDL: consider familial hypercholesterolemia workup")
        if key == "triglycerides" and value > 500:
            notes.append("Severe hypertriglyceridemia: pancreatitis risk")

        return "; ".join(notes) if notes else ""

    # ── Summary builder ─────────────────────────────────────────────────────

    def _build_summary(
        self,
        interpretations: List[Dict[str, Any]],
        risk_flags: List[str],
        patient_context: Dict[str, Any],
    ) -> str:
        """Build a human-readable summary of all interpretations."""
        total = len(interpretations)
        abnormal = sum(1 for i in interpretations if i.get("is_abnormal"))
        critical = sum(1 for i in interpretations if i.get("severity") == "critical")

        parts: List[str] = []
        parts.append(f"{total} lab(s) interpreted: {abnormal} abnormal, {critical} critical.")

        if critical:
            crits = [
                i["test_name"] for i in interpretations if i["severity"] == "critical"
            ]
            parts.append(f"Critical values: {', '.join(crits)}. Immediate attention required.")

        if not abnormal:
            parts.append("All results within normal limits.")

        return " ".join(parts)


# ── Factory ─────────────────────────────────────────────────────────────────

_instance: Optional[LabInterpreter] = None


def get_lab_interpreter() -> LabInterpreter:
    """Return a singleton LabInterpreter."""
    global _instance
    if _instance is None:
        _instance = LabInterpreter()
    return _instance
