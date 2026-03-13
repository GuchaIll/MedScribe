"""
Agent D — Record Compiler (Schema Mapper)

Purpose: Assemble canonical structured record from candidate facts with field provenance.
Deterministic work: Field mapping rules, merge duplicates, prefer higher confidence.
Hard constraint: Only compile from candidates with evidence.

DB integration:
  - Pre-seeds patient demographics from patient_record_fields (DB-loaded)
  - Merges with prior record baseline so returning patients keep their history
"""

from typing import Dict, List, Any, Optional
from ..state import GraphState


# Field mapping rules: fact_type -> record path
FACT_TYPE_MAPPING = {
    # Patient demographics
    "patient_name": ["patient", "name"],
    "patient_dob": ["patient", "dob"],
    "patient_age": ["patient", "age"],
    "patient_sex": ["patient", "sex"],
    "patient_mrn": ["patient", "mrn"],
    "patient_demographics": ["patient"],  # Composite
    
    # Allergies
    "allergy": ["allergies"],
    
    # Medications
    "medication": ["medications"],
    
    # Diagnoses
    "diagnosis": ["diagnoses"],
    
    # Vitals
    "vital": ["vitals"],
    
    # Labs
    "lab_result": ["labs"],
    
    # Procedures
    "procedure": ["procedures"],
    
    # Follow-ups
    "followup": ["followups"],
    
    # Problem list
    "problem_list": ["problems"],
}


def fill_structured_record_node(state: GraphState) -> GraphState:
    """
    Fill the structured clinical record from candidate facts and evidence.
    
    Agent D: Record Compiler
    - Pre-seeds patient demographics from DB (if available via patient_record_fields)
    - Maps candidate facts to structured record schema
    - Builds field-level provenance tracking
    - Merges duplicates (prefers higher confidence)
    - Only uses candidates that have evidence
    """
    state = state.copy() if isinstance(state, dict) else state
    
    candidates = state.get("candidate_facts", [])
    
    # Initialize empty record structure
    record = {
        "patient": {},
        "visit": {},
        "allergies": [],
        "medications": [],
        "diagnoses": [],
        "vitals": [],
        "labs": [],
        "procedures": [],
        "followups": [],
        "problems": [],
        "notes": {}
    }
    
    # ── Pre-seed from DB patient context ────────────────────────────────────
    prf = state.get("patient_record_fields") or {}
    demographics = prf.get("demographics", {})
    if demographics:
        record["patient"] = {
            "name": demographics.get("full_name", ""),
            "dob": demographics.get("dob", ""),
            "age": demographics.get("age"),
            "sex": demographics.get("sex", ""),
            "mrn": demographics.get("mrn", ""),
        }
        print(f"[Fill Record] Pre-seeded patient demographics from DB: {record['patient'].get('name', 'N/A')}")

    # Merge prior record baseline (returning patient)
    prior_record = prf.get("prior_record", {})
    if prior_record:
        # Carry forward list-type fields from prior record as baseline
        for list_field in ("allergies", "medications", "diagnoses", "problems"):
            prior_items = prior_record.get(list_field, [])
            if prior_items and isinstance(prior_items, list):
                for item in prior_items:
                    if isinstance(item, dict):
                        item.setdefault("source", "prior_record")
                        item.setdefault("confidence", 0.8)  # High confidence for DB records
                record[list_field] = list(prior_items)
        print(f"[Fill Record] Merged {sum(len(prior_record.get(f, [])) for f in ('allergies', 'medications', 'diagnoses', 'problems'))} items from prior record")
    
    provenance: List[Dict[str, Any]] = []
    
    # Track what we've seen to handle duplicates
    seen_items: Dict[str, Dict[str, Any]] = {}
    
    # Process each candidate
    for candidate in candidates:
        fact_type = candidate.get("type", candidate.get("fact_type", ""))
        value = candidate.get("value", {})
        confidence = candidate.get("confidence", 0.5)
        # Support both new (provenance.evidence) and legacy (evidence) shapes
        prov = candidate.get("provenance", {})
        if isinstance(prov, dict) and prov.get("evidence"):
            evidence = prov["evidence"]
        else:
            evidence = candidate.get("evidence", [])
        
        # Skip candidates without evidence (hard constraint)
        if not evidence:
            continue
        
        # Map to record structure
        if fact_type == "patient_demographics":
            _fill_patient_demographics(record, value, confidence, evidence, provenance)
        
        elif fact_type in ["patient_name", "patient_dob", "patient_age", "patient_sex", "patient_mrn"]:
            _fill_patient_field(record, fact_type, value, confidence, evidence, provenance)
        
        elif fact_type == "allergy":
            _append_unique_to_list(
                record, "allergies", value, confidence, evidence, provenance,
                "substance", seen_items
            )
        
        elif fact_type == "medication":
            _append_unique_to_list(
                record, "medications", value, confidence, evidence, provenance,
                "name", seen_items
            )
        
        elif fact_type == "diagnosis":
            _append_unique_to_list(
                record, "diagnoses", value, confidence, evidence, provenance,
                "code", seen_items
            )
        
        elif fact_type == "vital":
            _append_to_list(
                record, "vitals", value, confidence, evidence, provenance
            )
        
        elif fact_type == "lab_result":
            _append_unique_to_list(
                record, "labs", value, confidence, evidence, provenance,
                "test", seen_items
            )
        
        elif fact_type == "procedure":
            _append_unique_to_list(
                record, "procedures", value, confidence, evidence, provenance,
                "name", seen_items
            )
        
        elif fact_type == "followup":
            _append_to_list(
                record, "followups", value, confidence, evidence, provenance
            )
        
        elif fact_type == "problem_list":
            _append_unique_to_list(
                record, "problems", value, confidence, evidence, provenance,
                "name", seen_items
            )
    
    # Update state
    state["structured_record"] = record
    state["provenance"] = provenance
    
    # Track node execution
    if "controls" not in state:
        state["controls"] = {"attempts": {}, "budget": {}, "trace_log": []}
    state["controls"]["attempts"]["fill_structured_record"] = \
        state["controls"]["attempts"].get("fill_structured_record", 0) + 1
    
    print(f"[Fill Record] Compiled {len(candidates)} candidates into structured record")
    print(f"  - Allergies: {len(record['allergies'])}")
    print(f"  - Medications: {len(record['medications'])}")
    print(f"  - Diagnoses: {len(record['diagnoses'])}")
    print(f"  - Vitals: {len(record['vitals'])}")
    print(f"  - Labs: {len(record['labs'])}")
    
    return state


def _fill_patient_demographics(record: Dict, value: Dict, confidence: float, 
                                evidence: List, provenance: List):
    """Fill patient demographics from composite value."""
    for field in ["name", "dob", "age", "sex", "mrn"]:
        if field in value:
            record["patient"][field] = value[field]
            provenance.append({
                "field_path": f"patient.{field}",
                "evidence": evidence,
                "confidence": confidence
            })


def _fill_patient_field(record: Dict, fact_type: str, value: Any, confidence: float,
                        evidence: List, provenance: List):
    """Fill a single patient field."""
    field_name = fact_type.replace("patient_", "")
    
    # Handle both simple values and dict values
    if isinstance(value, dict):
        actual_value = value.get(field_name, value.get("value"))
    else:
        actual_value = value
    
    if actual_value is not None:
        record["patient"][field_name] = actual_value
        provenance.append({
            "field_path": f"patient.{field_name}",
            "evidence": evidence,
            "confidence": confidence
        })


def _append_to_list(record: Dict, list_name: str, value: Dict, confidence: float,
                    evidence: List, provenance: List):
    """Append item to list without duplicate checking."""
    if isinstance(value, dict):
        value["confidence"] = confidence
    
    record[list_name].append(value)
    
    idx = len(record[list_name]) - 1
    provenance.append({
        "field_path": f"{list_name}[{idx}]",
        "evidence": evidence,
        "confidence": confidence
    })


def _append_unique_to_list(record: Dict, list_name: str, value: Dict, confidence: float,
                           evidence: List, provenance: List, merge_key: str,
                           seen_items: Dict):
    """
    Append item to list with duplicate detection and merging.
    Prefers higher confidence when merging duplicates.
    """
    # Get merge key value
    merge_value = value.get(merge_key)
    if not merge_value:
        # No merge key, just append
        _append_to_list(record, list_name, value, confidence, evidence, provenance)
        return
    
    # Check if we've seen this before
    seen_key = f"{list_name}:{merge_value}"
    
    if seen_key in seen_items:
        existing = seen_items[seen_key]
        existing_confidence = existing.get("confidence", 0.0)
        
        # Merge: prefer higher confidence
        if confidence > existing_confidence:
            # Replace with higher confidence version
            idx = existing.get("index")
            value["confidence"] = confidence
            record[list_name][idx] = value
            
            # Update provenance
            for i, prov in enumerate(provenance):
                if prov["field_path"] == f"{list_name}[{idx}]":
                    provenance[i] = {
                        "field_path": f"{list_name}[{idx}]",
                        "evidence": evidence,
                        "confidence": confidence
                    }
                    break
            
            # Update seen_items
            seen_items[seen_key] = {
                "confidence": confidence,
                "index": idx,
                "value": value
            }
        else:
            # Keep existing (higher confidence), but could merge fields
            idx = existing.get("index")
            existing_item = record[list_name][idx]
            
            # Merge additional fields that don't exist
            for key, val in value.items():
                if key not in existing_item or not existing_item[key]:
                    existing_item[key] = val
    else:
        # First time seeing this, append it
        value["confidence"] = confidence
        record[list_name].append(value)
        idx = len(record[list_name]) - 1
        
        provenance.append({
            "field_path": f"{list_name}[{idx}]",
            "evidence": evidence,
            "confidence": confidence
        })
        
        seen_items[seen_key] = {
            "confidence": confidence,
            "index": idx,
            "value": value
        }
