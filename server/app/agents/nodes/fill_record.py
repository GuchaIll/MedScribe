"""
Agent D â€” Record Compiler (Schema Mapper)

DB-first precedence rules
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
â€¢ Single-value fields (name, dob, sex, mrn, contact_info, insurance, vitals
  scalar values): if the DB already provided a value, the extracted value is
  stored as a _conflict entry and the DB value is kept unchanged.

â€¢ List/appendable fields (chronic_conditions, medications, allergies,
  problem_list, hpi, family_history, risk_factors, labs, procedures,
  diagnoses): DB baseline is kept; new extracted items are appended only
  when they are not already present (case-insensitive name/substance match).

Conflict & certainty metadata
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  record["_conflicts"]       â€” [{field, db_value, extracted_value, confidence}]
  record["_low_confidence"]  â€” [{field, value, confidence}]       (conf < 0.7)
  record["_db_seeded_fields"]â€” [field_path, ...]

LOW_CONFIDENCE_THRESHOLD = 0.70
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from ..state import GraphState
from .record_schema import empty_record

LOW_CONFIDENCE_THRESHOLD = 0.70


# ── Public node ───────────────────────────────────────────────────────────────

def fill_structured_record_node(state: GraphState) -> GraphState:
    """
    Fill the hierarchical clinical record from candidate facts + DB context.
    DB values win on scalar fields; lists are appended (dedup by name/substance).
    """
    state = state.copy() if isinstance(state, dict) else state
    record: Dict[str, Any] = empty_record()
    candidates: List[Dict[str, Any]] = state.get("candidate_facts", [])
    _seed_from_db(record, state.get("patient_record_fields") or {})

    for candidate in candidates:
        if not _has_evidence(candidate):
            continue
        _apply_candidate(record, candidate)

    _derive_bmi(record)
    state["structured_record"] = record

    if "controls" not in state:
        state["controls"] = {"attempts": {}, "budget": {}, "trace_log": []}
    state["controls"]["attempts"]["fill_structured_record"] = (
        state["controls"]["attempts"].get("fill_structured_record", 0) + 1
    )
    _print_summary(record, candidates)
    return state


# ── DB seeding ────────────────────────────────────────────────────────────────

def _seed_from_db(record: Dict, prf: Dict) -> None:
    if not prf:
        return
    demo = prf.get("demographics", {})
    if demo:
        dem = record["demographics"]
        for src_key, dst_key in [
            ("full_name", "full_name"), ("dob", "date_of_birth"),
            ("date_of_birth", "date_of_birth"), ("sex", "sex"), ("mrn", "mrn"),
        ]:
            if demo.get(src_key) and not dem.get(dst_key):
                dem[dst_key] = demo[src_key]
                record["_db_seeded_fields"].append(f"demographics.{dst_key}")
        for sub, fields in [
            ("contact_info",      ("phone", "email", "address", "city", "state", "zip")),
            ("insurance",         ("provider", "policy_number", "group_number", "subscriber_name")),
            ("emergency_contact", ("name", "relationship", "phone")),
        ]:
            src_sub = demo.get(sub, {})
            if src_sub:
                for k in fields:
                    if src_sub.get(k) and not dem[sub].get(k):
                        dem[sub][k] = src_sub[k]

    prior = prf.get("prior_record", {})
    if prior:
        for section, target_path, _key in [
            ("chronic_conditions", ("past_medical_history", "chronic_conditions"), "name"),
            ("medications",         ("medications",),                              "name"),
            ("allergies",           ("allergies",),                                "substance"),
        ]:
            items = prior.get(section, [])
            tgt: Any = record
            for p in target_path:
                tgt = tgt[p]
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("source", "prior_record")
                    item.setdefault("confidence", 0.85)
                    tgt.append(item)
        for prob in prior.get("problem_list", []):
            if isinstance(prob, dict):
                prob.setdefault("source", "prior_record")
                prob.setdefault("confidence", 0.85)
                record["problem_list"].append(prob)


# ── Candidate dispatcher ──────────────────────────────────────────────────────

_SCALAR_DEMO: Dict[str, Tuple[str, str]] = {
    "patient_name": ("demographics", "full_name"),
    "patient_dob":  ("demographics", "date_of_birth"),
    "patient_sex":  ("demographics", "sex"),
    "patient_mrn":  ("demographics", "mrn"),
}

_VITALS_KEYS = {
    "blood_pressure", "heart_rate", "respiratory_rate", "temperature",
    "spo2", "height", "weight", "bmi",
}
_VITALS_ALIASES: Dict[str, str] = {
    "bp": "blood_pressure", "hr": "heart_rate", "rr": "respiratory_rate",
    "temp": "temperature", "o2": "spo2", "o2sat": "spo2", "wt": "weight", "ht": "height",
}
_SOCIAL_KEYS = {"tobacco", "alcohol", "drug_use", "occupation", "exercise", "diet", "sexual_activity"}
_ROS_KEYS = {
    "cardiovascular", "respiratory", "neurological", "gastrointestinal",
    "musculoskeletal", "dermatological", "psychiatric", "endocrine",
    "genitourinary", "hematologic",
}
_EXAM_KEYS = {
    "general", "cardiovascular", "respiratory", "neurological",
    "abdomen", "musculoskeletal", "skin", "head_neck",
}


def _apply_candidate(record: Dict, candidate: Dict) -> None:  # noqa: C901
    fact_type = candidate.get("type", candidate.get("fact_type", "")).lower()
    value     = candidate.get("value", {})
    conf      = float(candidate.get("confidence", 0.5))

    # ── Demographics (scalar) ──────────────────────────────────────────────
    if fact_type in _SCALAR_DEMO:
        section_name, field = _SCALAR_DEMO[fact_type]
        ev = value if not isinstance(value, dict) else (value.get(field) or value.get("value"))
        _set_scalar(record, f"{section_name}.{field}", record[section_name], field, ev, conf)
        return

    if fact_type == "patient_demographics" and isinstance(value, dict):
        for sf, (section_name, field) in _SCALAR_DEMO.items():
            sv = value.get(field) or value.get(sf.replace("patient_", ""))
            if sv:
                _set_scalar(record, f"{section_name}.{field}", record[section_name], field, sv, conf)
        return

    # ── Chief complaint ────────────────────────────────────────────────────
    if fact_type == "chief_complaint":
        cc = record["chief_complaint"]
        if isinstance(value, dict):
            for k in ("free_text", "onset", "duration", "severity", "location"):
                if value.get(k) and not cc.get(k):
                    cc[k] = value[k]
        elif isinstance(value, str) and not cc["free_text"]:
            cc["free_text"] = value
        _flag_low_confidence(record, "chief_complaint.free_text", cc.get("free_text"), conf)
        return

    # ── HPI ────────────────────────────────────────────────────────────────
    if fact_type in ("hpi_event", "hpi"):
        if isinstance(value, dict) and value.get("symptom"):
            entry: Dict[str, Any] = {k: value.get(k) for k in (
                "symptom", "onset", "progression", "triggers",
                "relieving_factors", "associated_symptoms", "timeline", "timestamp"
            )}
            entry["confidence"] = conf
            if not _already_in_list(record["hpi"], "symptom", entry["symptom"]):
                record["hpi"].append(entry)
        return

    # ── Chronic conditions ─────────────────────────────────────────────────
    if fact_type == "chronic_condition":
        conds = record["past_medical_history"]["chronic_conditions"]
        name = (_coerce_str(value, "name") or _coerce_str(value, "condition")
                if isinstance(value, dict) else str(value))
        if name and not _already_in_list(conds, "name", name):
            e: Dict[str, Any] = {"name": name, "confidence": conf, "source": "extracted"}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("icd10_code", "onset_year", "status") if value.get(k)})
            conds.append(e)
            _flag_low_confidence(record, f"pmh.chronic_conditions.{name}", name, conf)
        return

    if fact_type == "hospitalization":
        if isinstance(value, dict):
            value["confidence"] = conf
            record["past_medical_history"]["hospitalizations"].append(value)
        return

    if fact_type == "surgery":
        surgs = record["past_medical_history"]["surgeries"]
        name = _coerce_str(value, "name") if isinstance(value, dict) else str(value)
        if name and not _already_in_list(surgs, "name", name):
            e = {"name": name, "confidence": conf}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("date", "facility") if value.get(k)})
            surgs.append(e)
        return

    # ── Medications ────────────────────────────────────────────────────────
    if fact_type == "medication":
        meds = record["medications"]
        name = _coerce_str(value, "name") if isinstance(value, dict) else str(value)
        if not name:
            return
        if not _already_in_list(meds, "name", name):
            e = {"name": name, "confidence": conf, "source": "extracted"}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("dose", "route", "frequency", "indication", "start_date")
                          if value.get(k)})
            meds.append(e)
            _flag_low_confidence(record, f"medications.{name}", name, conf)
        else:
            _enrich_list_item(meds, "name", name, value,
                              ("dose", "route", "frequency", "indication"), conf)
        return

    # ── Allergies ──────────────────────────────────────────────────────────
    if fact_type == "allergy":
        allergies = record["allergies"]
        substance = _coerce_str(value, "substance") if isinstance(value, dict) else str(value)
        if substance and not _already_in_list(allergies, "substance", substance):
            e = {"substance": substance, "confidence": conf, "source": "extracted"}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("reaction", "severity", "category") if value.get(k)})
            allergies.append(e)
        return

    # ── Family history ─────────────────────────────────────────────────────
    if fact_type == "family_history":
        fh = record["family_history"]
        member = _coerce_str(value, "member") if isinstance(value, dict) else str(value)
        if not member:
            return
        existing = next((x for x in fh if x.get("member", "").lower() == member.lower()), None)
        if existing:
            for c in (value.get("conditions") or [] if isinstance(value, dict) else []):
                if c not in existing.setdefault("conditions", []):
                    existing["conditions"].append(c)
            for k in ("alive", "age_at_death", "cause_of_death"):
                if isinstance(value, dict) and value.get(k) is not None and existing.get(k) is None:
                    existing[k] = value[k]
        else:
            e = {"member": member, "confidence": conf, "conditions": []}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("conditions", "alive", "age_at_death", "cause_of_death")
                          if value.get(k) is not None})
            fh.append(e)
        return

    # ── Social history ─────────────────────────────────────────────────────
    if fact_type == "social_history":
        sh = record["social_history"]
        if isinstance(value, dict):
            cat = (value.get("category") or "").lower()
            if cat in _SOCIAL_KEYS and not sh.get(cat):
                sh[cat] = value.get("value") or value.get("details")
            else:
                for k in _SOCIAL_KEYS:
                    if value.get(k) and not sh.get(k):
                        sh[k] = value[k]
        return

    # ── Review of systems ─────────────────────────────────────────────────
    if fact_type in ("ros_finding", "review_of_systems", "ros"):
        ros = record["review_of_systems"]
        if isinstance(value, dict):
            system = (value.get("system") or "").lower()
            finding = value.get("finding") or value.get("value")
            if system in _ROS_KEYS and finding and not ros.get(system):
                ros[system] = finding
            else:
                for k in _ROS_KEYS:
                    if value.get(k) and not ros.get(k):
                        ros[k] = value[k]
        return

    # ── Vitals ─────────────────────────────────────────────────────────────
    if fact_type == "vital":
        vitals = record["vitals"]
        if isinstance(value, dict):
            vtype = (value.get("type") or value.get("vital_type") or "").lower().replace(" ", "_")
            vtype = _VITALS_ALIASES.get(vtype, vtype)
            if vtype in _VITALS_KEYS:
                _set_scalar(record, f"vitals.{vtype}", vitals, vtype, _format_vital(value), conf)
            else:
                for k in _VITALS_KEYS:
                    if value.get(k) and not vitals.get(k):
                        vitals[k] = str(value[k])
        return

    # ── Physical exam ─────────────────────────────────────────────────────
    if fact_type in ("physical_exam", "physical_exam_finding"):
        pe = record["physical_exam"]
        if isinstance(value, dict):
            system = (value.get("system") or "").lower()
            finding = value.get("finding") or value.get("value")
            if system in _EXAM_KEYS and finding and not pe.get(system):
                pe[system] = finding
            else:
                for k in _EXAM_KEYS:
                    if value.get(k) and not pe.get(k):
                        pe[k] = value[k]
        return

    # ── Labs ───────────────────────────────────────────────────────────────
    if fact_type == "lab_result":
        labs = record["labs"]
        test = (_coerce_str(value, "test") or _coerce_str(value, "test_name")
                if isinstance(value, dict) else str(value))
        if not test:
            return
        if _already_in_list(labs, "test", test):
            _enrich_list_item(labs, "test", test, value,
                              ("value", "unit", "reference_range", "date", "abnormal"), conf)
        else:
            e = {"test": test, "confidence": conf}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("value", "unit", "reference_range", "date", "abnormal")
                          if value.get(k) is not None})
            labs.append(e)
            _flag_low_confidence(record, f"labs.{test}", e.get("value"), conf)
        return

    # ── Diagnoses ─────────────────────────────────────────────────────────
    if fact_type == "diagnosis":
        diagnoses = record["diagnoses"]
        desc = (_coerce_str(value, "description") or _coerce_str(value, "desc")
                if isinstance(value, dict) else str(value))
        code = _coerce_str(value, "code") if isinstance(value, dict) else None
        key = desc or code
        if key and not _already_in_list(diagnoses, "description", key):
            e = {"confidence": conf}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("code", "description") if value.get(k)})
            diagnoses.append(e)
        return

    # ── Problem list ───────────────────────────────────────────────────────
    if fact_type in ("problem_list", "problem"):
        probs = record["problem_list"]
        name = _coerce_str(value, "name") if isinstance(value, dict) else str(value)
        if name and not _already_in_list(probs, "name", name):
            e = {"name": name, "confidence": conf, "source": "extracted"}
            if isinstance(value, dict) and value.get("status"):
                e["status"] = value["status"]
            probs.append(e)
        return

    # ── Risk factors ───────────────────────────────────────────────────────
    if fact_type == "risk_factor":
        rfs = record["risk_factors"]
        name = _coerce_str(value, "name") if isinstance(value, dict) else str(value)
        if name and not _already_in_list(rfs, "name", name):
            e = {"name": name, "confidence": conf}
            if isinstance(value, dict):
                e.update({k: value[k] for k in ("severity", "source") if value.get(k)})
            rfs.append(e)
        return

    # ── Assessment ─────────────────────────────────────────────────────────
    if fact_type == "assessment":
        assess = record["assessment"]
        if isinstance(value, dict):
            for dx in (value.get("likely_diagnoses") or []):
                if dx not in assess["likely_diagnoses"]:
                    assess["likely_diagnoses"].append(dx)
            for dx in (value.get("differential_diagnoses") or []):
                if dx not in assess["differential_diagnoses"]:
                    assess["differential_diagnoses"].append(dx)
            if value.get("clinical_reasoning") and not assess.get("clinical_reasoning"):
                assess["clinical_reasoning"] = value["clinical_reasoning"]
        elif isinstance(value, str) and not assess["clinical_reasoning"]:
            assess["clinical_reasoning"] = value
        return

    # ── Plan ───────────────────────────────────────────────────────────────
    if fact_type == "plan":
        plan = record["plan"]
        if isinstance(value, dict):
            for k in ("medications_prescribed", "tests_ordered",
                      "lifestyle_recommendations", "referrals"):
                for item in (value.get(k) or []):
                    if item and item not in plan[k]:
                        plan[k].append(item)
            if value.get("follow_up") and not plan["follow_up"]:
                plan["follow_up"] = value["follow_up"]
        return

    # ── Procedures / follow-ups ────────────────────────────────────────────
    if fact_type == "procedure":
        procs = record["procedures"]
        name = _coerce_str(value, "name") if isinstance(value, dict) else str(value)
        if name and not _already_in_list(procs, "name", name):
            e = {"name": name, "confidence": conf}
            if isinstance(value, dict) and value.get("date"):
                e["date"] = value["date"]
            procs.append(e)
        return

    if fact_type == "followup":
        plan = record["plan"]
        desc = _coerce_str(value, "description") if isinstance(value, dict) else str(value)
        if desc:
            plan["follow_up"] = (
                (plan["follow_up"] or "") + ("; " if plan["follow_up"] else "") + desc
            )
        return


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_evidence(candidate: Dict) -> bool:
    prov = candidate.get("provenance", {})
    if isinstance(prov, dict):
        return bool(prov.get("evidence"))
    return bool(candidate.get("evidence"))


def _set_scalar(record: Dict, field_path: str, section: Dict, field: str,
                extracted_value: Any, confidence: float) -> None:
    """DB-first: if a DB-seeded value exists and differs, record conflict."""
    if not extracted_value:
        return
    existing = section.get(field)
    if existing and field_path in record.get("_db_seeded_fields", []):
        if str(existing).lower().strip() != str(extracted_value).lower().strip():
            record["_conflicts"].append({
                "field": field_path, "db_value": existing,
                "extracted_value": extracted_value, "confidence": confidence,
            })
    else:
        if not existing:
            section[field] = extracted_value
            _flag_low_confidence(record, field_path, extracted_value, confidence)


def _flag_low_confidence(record: Dict, field_path: str, value: Any, confidence: float) -> None:
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        record["_low_confidence"].append(
            {"field": field_path, "value": value, "confidence": confidence}
        )


def _already_in_list(lst: List[Dict], key: str, value: str) -> bool:
    return any(str(item.get(key, "")).lower() == str(value).lower()
               for item in lst if isinstance(item, dict))


def _coerce_str(d: Dict, key: str) -> Optional[str]:
    v = d.get(key)
    return str(v).strip() if v else None


def _enrich_list_item(lst: List[Dict], match_key: str, match_value: str,
                       new_value: Any, fields: tuple, confidence: float) -> None:
    """Add missing sub-fields; never overwrite; upgrade confidence if higher."""
    for item in lst:
        if isinstance(item, dict) and str(item.get(match_key, "")).lower() == match_value.lower():
            if isinstance(new_value, dict):
                for f in fields:
                    if new_value.get(f) and not item.get(f):
                        item[f] = new_value[f]
            if confidence > item.get("confidence", 0):
                item["confidence"] = confidence
            return


def _format_vital(value: Dict) -> str:
    v = value.get("value", "")
    unit = value.get("unit", "")
    return f"{v} {unit}".strip() if unit else str(v)


def _derive_bmi(record: Dict) -> None:
    vitals = record["vitals"]
    if vitals.get("bmi"):
        return
    try:
        import re
        h_str = str(vitals.get("height", ""))
        w_str = str(vitals.get("weight", ""))
        h_m = re.search(r"(\d+\.?\d*)\s*(cm)?", h_str, re.I)
        w_k = re.search(r"(\d+\.?\d*)\s*(kg|lbs?)?", w_str, re.I)
        if not h_m or not w_k:
            return
        hv, hu = float(h_m.group(1)), (h_m.group(2) or "cm").lower()
        wv, wu = float(w_k.group(1)), (w_k.group(2) or "kg").lower()
        if hu == "cm":
            hv /= 100
        if wu in ("lbs", "lb"):
            wv *= 0.453592
        if hv > 0:
            vitals["bmi"] = f"{wv / (hv ** 2):.1f}"
    except Exception:
        pass


def _print_summary(record: Dict, candidates: List) -> None:
    pmh = record.get("past_medical_history", {})
    print(
        f"[Fill Record] {len(candidates)} candidates → "
        f"name={record['demographics']['full_name'] or '?'}, "
        f"chronic={len(pmh.get('chronic_conditions', []))}, "
        f"meds={len(record['medications'])}, allergies={len(record['allergies'])}, "
        f"labs={len(record['labs'])}, hpi={len(record['hpi'])}, "
        f"conflicts={len(record['_conflicts'])}, low_conf={len(record['_low_confidence'])}"
    )

