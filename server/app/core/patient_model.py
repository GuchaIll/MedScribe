"""
Patient Longitudinal Model Service.

Provides trend analysis, risk scoring, and timeline computation
across a patient's full visit / record history:

  - Lab trend analysis (direction, slope, latest status)
  - Medication timeline with adherence estimates
  - Composite risk scoring
  - Unified patient profile
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PatientModel:
    """
    Longitudinal patient analytics.

    All public methods accept pre-aggregated data so the model
    can be used without a live DB connection (useful for tests and
    the in-memory session path).
    """

    # ── Lab Trends ─────────────────────────────────────────────────────────

    @staticmethod
    def compute_lab_trends(
        lab_history: List[Dict[str, Any]],
        *,
        min_points: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Group historical lab values by test name and compute trends.

        Parameters
        ----------
        lab_history : list[dict]
            Each item: {test_name, value, unit, date, abnormal?, reference_range}
        min_points : int
            Minimum data points to compute a trend direction.

        Returns
        -------
        list[dict]
            One entry per test name with data_points, trend_direction,
            latest_value, latest_status, unit.
        """
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for lab in lab_history:
            name = (lab.get("test_name") or "").strip()
            if not name:
                continue
            grouped[name].append(lab)

        trends: List[Dict[str, Any]] = []

        for test_name, entries in grouped.items():
            # Sort by date ascending
            sorted_entries = sorted(
                entries,
                key=lambda x: _parse_date(x.get("date", "")),
            )

            data_points = []
            for e in sorted_entries:
                val = _safe_float(e.get("value"))
                if val is not None:
                    data_points.append({
                        "date": e.get("date", ""),
                        "value": val,
                        "unit": e.get("unit", ""),
                        "abnormal": e.get("abnormal", False),
                    })

            latest = data_points[-1] if data_points else None

            direction = "insufficient_data"
            if len(data_points) >= min_points:
                direction = _trend_direction([p["value"] for p in data_points])

            trends.append({
                "test_name": test_name,
                "data_points": data_points,
                "trend_direction": direction,
                "latest_value": latest["value"] if latest else None,
                "latest_status": "abnormal" if (latest and latest.get("abnormal")) else "normal",
                "unit": latest["unit"] if latest else "",
            })

        return trends

    # ── Medication Timeline ────────────────────────────────────────────────

    @staticmethod
    def compute_medication_timeline(
        medication_history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build a medication timeline with simple adherence heuristics.

        Parameters
        ----------
        medication_history : list[dict]
            Each item: {name, dose, route, frequency, status, last_recorded}

        Returns
        -------
        dict  {medications, total_active, total_discontinued, adherence_score}
        """
        med_map: Dict[str, Dict[str, Any]] = {}

        for med in medication_history:
            name = (med.get("name") or "").strip().lower()
            if not name:
                continue

            existing = med_map.get(name)
            entry = {
                "name": med.get("name", ""),
                "dose": med.get("dose"),
                "route": med.get("route"),
                "frequency": med.get("frequency"),
                "status": med.get("status", "active"),
                "first_recorded": (
                    existing["first_recorded"]
                    if existing
                    else med.get("last_recorded", "")
                ),
                "last_recorded": med.get("last_recorded", ""),
            }
            med_map[name] = entry

        meds = list(med_map.values())
        active = [m for m in meds if m["status"] == "active"]
        discontinued = [m for m in meds if m["status"] != "active"]

        # Simple adherence heuristic: if a medication appeared in the last
        # 3 visits we assume it is compliant (no gap).  More sophisticated
        # logic would compare scheduled refills.
        adherence_score = 1.0 if not active else round(
            min(1.0, len(active) / max(len(meds), 1)), 2
        )

        return {
            "medications": meds,
            "total_active": len(active),
            "total_discontinued": len(discontinued),
            "adherence_score": adherence_score,
        }

    # ── Risk Scoring ───────────────────────────────────────────────────────

    @staticmethod
    def compute_risk_score(
        patient_info: Dict[str, Any],
        diagnoses: List[Dict[str, Any]],
        medications: List[Dict[str, Any]],
        labs: List[Dict[str, Any]],
        visit_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Compute a weighted composite risk score.

        Parameters
        ----------
        patient_info : dict  {age, sex, …}
        diagnoses, medications, labs : list[dict]
        visit_count : int

        Returns
        -------
        dict  {score (0-100), level, factors}
        """
        score = 0.0
        factors: List[str] = []

        # ── Age-based risk ──
        age = patient_info.get("age")
        if age is not None:
            if age >= 75:
                score += 15
                factors.append(f"Elderly patient (age {age})")
            elif age >= 65:
                score += 8
                factors.append(f"Senior patient (age {age})")
            elif age >= 50:
                score += 3

        # ── Chronic conditions ──
        HIGH_RISK_KEYWORDS = {
            "diabetes": 10, "hypertension": 7, "ckd": 12, "chronic kidney": 12,
            "heart failure": 14, "copd": 10, "cancer": 15, "stroke": 12,
            "cirrhosis": 12, "atrial fibrillation": 8, "coronary artery": 10,
            "hiv": 8, "hepatitis": 7, "dementia": 8,
        }
        for dx in diagnoses:
            desc = (dx.get("description") or "").lower()
            for kw, weight in HIGH_RISK_KEYWORDS.items():
                if kw in desc:
                    score += weight
                    factors.append(f"Condition: {dx.get('description')}")
                    break

        # ── Polypharmacy ──
        active_meds = [m for m in medications if m.get("status", "active") == "active"]
        n = len(active_meds)
        if n > 10:
            score += 12
            factors.append(f"Polypharmacy — {n} active meds")
        elif n > 5:
            score += 5
            factors.append(f"Multiple medications ({n})")

        # ── Allergies in record (proxy for complexity) ──
        # We don't independently receive allergies here, so skip.

        # ── Abnormal labs ──
        abnormal = [l for l in labs if l.get("abnormal")]
        if len(abnormal) > 5:
            score += 10
            factors.append(f"{len(abnormal)} abnormal lab results")
        elif len(abnormal) > 2:
            score += 5
            factors.append(f"{len(abnormal)} abnormal lab results")

        # ── Frequent visits ──
        if visit_count > 12:
            score += 5
            factors.append(f"Frequent visits ({visit_count})")

        # Cap at 100
        score = min(int(score), 100)

        if score >= 50:
            level = "high"
        elif score >= 25:
            level = "moderate"
        else:
            level = "low"

        return {
            "score": score,
            "level": level,
            "factors": factors,
            "computed_at": datetime.utcnow().isoformat(),
        }

    # ── Unified Profile ────────────────────────────────────────────────────

    @classmethod
    def build_patient_profile(
        cls,
        patient_info: Dict[str, Any],
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Compile a full longitudinal profile from raw patient + record data.

        Parameters
        ----------
        patient_info : dict    {patient_id, mrn, full_name, dob, age, sex}
        records : list[dict]   Each item is the structured_data JSON from a MedicalRecord.

        Returns
        -------
        dict  Matches PatientProfileResponse schema.
        """
        all_labs: List[Dict[str, Any]] = []
        all_meds: List[Dict[str, Any]] = []
        all_diagnoses: List[Dict[str, Any]] = []

        for rec in records:
            # labs
            for lab in rec.get("labs", []):
                if isinstance(lab, dict):
                    all_labs.append(lab)
            # meds
            for med in rec.get("medications", []):
                if isinstance(med, dict):
                    all_meds.append(med)
            # diagnoses
            for dx in rec.get("diagnoses", []):
                if isinstance(dx, dict):
                    all_diagnoses.append(dx)

        lab_trends = cls.compute_lab_trends(all_labs)
        med_timeline = cls.compute_medication_timeline(all_meds)
        risk = cls.compute_risk_score(
            patient_info=patient_info,
            diagnoses=all_diagnoses,
            medications=all_meds,
            labs=all_labs,
            visit_count=len(records),
        )

        return {
            "patient_id": patient_info.get("patient_id") or patient_info.get("id", ""),
            "patient_info": patient_info,
            "lab_trends": lab_trends,
            "medication_timeline": med_timeline,
            "risk_score": risk,
            "visit_count": len(records),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> datetime:
    """Best-effort ISO date parse with fallback."""
    if not raw:
        return datetime.min
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.min


def _safe_float(v: Any) -> Optional[float]:
    """Try converting a value to float."""
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _trend_direction(values: List[float]) -> str:
    """
    Determine trend from a list of chronological numeric values.

    Returns one of: increasing, decreasing, stable, fluctuating
    """
    if len(values) < 2:
        return "insufficient_data"

    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    avg_diff = sum(diffs) / len(diffs)
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)

    ratio = len(diffs)
    # If >60% are in the same direction, call it a trend
    if pos / ratio >= 0.6:
        return "increasing"
    if neg / ratio >= 0.6:
        return "decreasing"

    # Check if the range of values is < 10% of the mean → stable
    mean = sum(values) / len(values)
    if mean != 0:
        spread = (max(values) - min(values)) / abs(mean)
        if spread < 0.1:
            return "stable"

    return "fluctuating"
