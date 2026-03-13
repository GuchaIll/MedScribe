"""
Conflict detection between OCR-extracted fields and existing patient records.

Cross-references extracted data against:
  - Patient history (medications, allergies, diagnoses, labs)
  - Clinical safety rules (allergy-drug, drug-drug, dosage range)
  - Internal consistency checks (duplicate fields, contradictions)

Produces ConflictItem objects for the modification queue.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .field_extractor import ExtractedField, FieldCategory

logger = logging.getLogger(__name__)


class ConflictType(str, Enum):
    """Types of conflicts detected."""
    ALLERGY_MEDICATION = "allergy_medication"
    DRUG_INTERACTION = "drug_interaction"
    DOSAGE_RANGE = "dosage_range"
    VALUE_OUT_OF_RANGE = "value_out_of_range"
    DEMOGRAPHIC_MISMATCH = "demographic_mismatch"
    DUPLICATE_MEDICATION = "duplicate_medication"
    CONTRADICTORY_VALUE = "contradictory_value"
    MISSING_REQUIRED = "missing_required"
    LOW_CONFIDENCE = "low_confidence"


class ConflictSeverity(str, Enum):
    """Severity levels for conflicts."""
    CRITICAL = "critical"      # Safety risk — must resolve
    HIGH = "high"              # Likely error — should resolve
    MEDIUM = "medium"          # Inconsistency — review recommended
    LOW = "low"                # Minor issue — informational


@dataclass
class ConflictItem:
    """A detected conflict between OCR-extracted data and existing records."""
    conflict_id: str = ""
    field_name: str = ""
    extracted_value: str = ""
    existing_value: str = ""
    conflict_type: ConflictType = ConflictType.LOW_CONFIDENCE
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    message: str = ""
    source_document: str = ""
    recommendation: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.conflict_id:
            import uuid
            self.conflict_id = f"cfl_{uuid.uuid4().hex[:12]}"


def detect_conflicts(
    extracted_fields: List[ExtractedField],
    patient_history: Optional[Dict[str, Any]] = None,
    *,
    confidence_threshold: float = 0.5,
) -> List[ConflictItem]:
    """
    Detect conflicts between extracted fields and patient records.

    Parameters
    ----------
    extracted_fields : list of ExtractedField
        Fields extracted from OCR pipeline.
    patient_history : dict, optional
        Patient history from PatientService.get_patient_history().
        Expected keys: medications, allergies, diagnoses, labs, patient_info.
    confidence_threshold : float
        Fields below this confidence are flagged as LOW_CONFIDENCE.

    Returns
    -------
    List[ConflictItem]
    """
    conflicts: List[ConflictItem] = []

    # 1. Low confidence fields
    conflicts.extend(_check_low_confidence(extracted_fields, confidence_threshold))

    # 2. Internal consistency—duplicates within extracted fields
    conflicts.extend(_check_internal_duplicates(extracted_fields))

    if patient_history and patient_history.get("found", False):
        # 3. Allergy-medication conflicts
        conflicts.extend(_check_allergy_conflicts(extracted_fields, patient_history))

        # 4. Drug interactions (new meds vs existing meds)
        conflicts.extend(_check_drug_interactions(extracted_fields, patient_history))

        # 5. Demographic mismatches
        conflicts.extend(_check_demographic_mismatches(extracted_fields, patient_history))

        # 6. Lab value range checks
        conflicts.extend(_check_lab_ranges(extracted_fields))

        # 7. Duplicate medications (new vs existing)
        conflicts.extend(_check_medication_duplicates(extracted_fields, patient_history))

    return conflicts


# ── Check functions ─────────────────────────────────────────────────────────

def _check_low_confidence(
    fields: List[ExtractedField],
    threshold: float,
) -> List[ConflictItem]:
    """Flag fields below the confidence threshold."""
    conflicts = []
    for f in fields:
        if f.confidence < threshold:
            conflicts.append(ConflictItem(
                field_name=f.field_name,
                extracted_value=str(f.value),
                conflict_type=ConflictType.LOW_CONFIDENCE,
                severity=ConflictSeverity.MEDIUM,
                message=f"Field '{f.field_name}' has low extraction confidence ({f.confidence:.2f})",
                source_document=f.source_document,
                recommendation="Verify this value manually during review.",
            ))
    return conflicts


def _check_internal_duplicates(
    fields: List[ExtractedField],
) -> List[ConflictItem]:
    """Check for contradictory values within the same extraction."""
    conflicts = []
    # Group by (category, field_name)
    groups: Dict[str, List[ExtractedField]] = {}
    for f in fields:
        key = f"{f.category.value}:{f.field_name.lower()}"
        groups.setdefault(key, []).append(f)

    for key, group in groups.items():
        if len(group) > 1:
            values = [str(f.value) for f in group]
            unique_values = set(v.lower().strip() for v in values)
            if len(unique_values) > 1:
                conflicts.append(ConflictItem(
                    field_name=group[0].field_name,
                    extracted_value=" vs ".join(values[:3]),
                    conflict_type=ConflictType.CONTRADICTORY_VALUE,
                    severity=ConflictSeverity.HIGH,
                    message=f"Multiple different values for '{group[0].field_name}': {', '.join(values[:3])}",
                    source_document=group[0].source_document,
                    recommendation="Verify which value is correct.",
                ))
    return conflicts


def _check_allergy_conflicts(
    fields: List[ExtractedField],
    history: Dict[str, Any],
) -> List[ConflictItem]:
    """Cross-reference extracted medications against known allergies."""
    conflicts = []
    known_allergies = history.get("allergies", [])
    if not known_allergies:
        return conflicts

    allergy_substances = {
        a["substance"].lower()
        for a in known_allergies
        if isinstance(a, dict) and a.get("substance")
    }

    # Cross-reactivity map (simplified — full version in clinical_suggestions.py)
    cross_reactive = {
        "penicillin": {"amoxicillin", "ampicillin", "augmentin", "piperacillin"},
        "sulfa": {"sulfamethoxazole", "sulfasalazine", "trimethoprim-sulfamethoxazole"},
        "cephalosporin": {"cephalexin", "ceftriaxone", "cefazolin"},
        "nsaid": {"ibuprofen", "naproxen", "aspirin", "diclofenac", "meloxicam"},
    }

    med_fields = [f for f in fields if f.category == FieldCategory.MEDICATION]

    for med in med_fields:
        med_name = str(med.value).lower().split()[0] if med.value else ""
        if not med_name:
            continue

        # Direct allergy match
        for allergen in allergy_substances:
            if allergen in med_name or med_name in allergen:
                conflicts.append(ConflictItem(
                    field_name=med.field_name,
                    extracted_value=str(med.value),
                    existing_value=f"Allergy: {allergen}",
                    conflict_type=ConflictType.ALLERGY_MEDICATION,
                    severity=ConflictSeverity.CRITICAL,
                    message=f"⚠️ ALLERGY CONFLICT: {med.value} prescribed but patient is allergic to {allergen}",
                    source_document=med.source_document,
                    recommendation=f"Do NOT administer {med.value}. Consult alternatives.",
                ))

        # Cross-reactivity check
        for allergen in allergy_substances:
            related_drugs = cross_reactive.get(allergen, set())
            if med_name in related_drugs:
                conflicts.append(ConflictItem(
                    field_name=med.field_name,
                    extracted_value=str(med.value),
                    existing_value=f"Allergy: {allergen} (cross-reactive)",
                    conflict_type=ConflictType.ALLERGY_MEDICATION,
                    severity=ConflictSeverity.CRITICAL,
                    message=f"⚠️ CROSS-REACTIVITY: {med.value} may cross-react with {allergen} allergy",
                    source_document=med.source_document,
                    recommendation=f"Patient is allergic to {allergen}. {med_name} has known cross-reactivity.",
                ))

    return conflicts


def _check_drug_interactions(
    fields: List[ExtractedField],
    history: Dict[str, Any],
) -> List[ConflictItem]:
    """Check for drug-drug interactions between new and existing medications."""
    conflicts = []
    existing_meds = {
        m["name"].lower()
        for m in history.get("medications", [])
        if isinstance(m, dict) and m.get("name")
    }

    # Known major interactions (simplified list)
    interaction_pairs = {
        frozenset({"warfarin", "aspirin"}): "Increased bleeding risk",
        frozenset({"warfarin", "ibuprofen"}): "Increased bleeding risk",
        frozenset({"warfarin", "naproxen"}): "Increased bleeding risk",
        frozenset({"metformin", "contrast"}): "Risk of lactic acidosis",
        frozenset({"digoxin", "amiodarone"}): "Digoxin toxicity risk",
        frozenset({"lisinopril", "potassium"}): "Hyperkalemia risk",
        frozenset({"lithium", "ibuprofen"}): "Lithium toxicity risk",
        frozenset({"methotrexate", "trimethoprim"}): "Bone marrow suppression",
        frozenset({"ssri", "maoi"}): "Serotonin syndrome risk",
        frozenset({"simvastatin", "clarithromycin"}): "Rhabdomyolysis risk",
    }

    new_meds = [f for f in fields if f.category == FieldCategory.MEDICATION]

    for med in new_meds:
        med_name = str(med.value).lower().split()[0] if med.value else ""
        if not med_name:
            continue

        for existing_med in existing_meds:
            pair = frozenset({med_name, existing_med})
            if pair in interaction_pairs:
                conflicts.append(ConflictItem(
                    field_name=med.field_name,
                    extracted_value=str(med.value),
                    existing_value=f"Current medication: {existing_med}",
                    conflict_type=ConflictType.DRUG_INTERACTION,
                    severity=ConflictSeverity.HIGH,
                    message=f"Drug interaction: {med_name} + {existing_med} — {interaction_pairs[pair]}",
                    source_document=med.source_document,
                    recommendation=f"Review interaction between {med_name} and {existing_med}.",
                ))

    return conflicts


def _check_demographic_mismatches(
    fields: List[ExtractedField],
    history: Dict[str, Any],
) -> List[ConflictItem]:
    """Check demographic fields against known patient info."""
    conflicts = []
    patient_info = history.get("patient_info", {})
    if not patient_info:
        return conflicts

    demo_fields = [f for f in fields if f.category == FieldCategory.DEMOGRAPHIC]

    for f in demo_fields:
        fname = f.field_name.lower()
        value = str(f.value).strip().lower()

        if fname in ("patient_name", "name") and patient_info.get("full_name"):
            existing = patient_info["full_name"].lower()
            if value and existing and value not in existing and existing not in value:
                conflicts.append(ConflictItem(
                    field_name=f.field_name,
                    extracted_value=str(f.value),
                    existing_value=patient_info["full_name"],
                    conflict_type=ConflictType.DEMOGRAPHIC_MISMATCH,
                    severity=ConflictSeverity.HIGH,
                    message=f"Name mismatch: extracted '{f.value}' vs existing '{patient_info['full_name']}'",
                    source_document=f.source_document,
                    recommendation="Verify patient identity. Document may belong to a different patient.",
                ))

        if fname in ("date_of_birth", "dob") and patient_info.get("dob"):
            existing_dob = patient_info["dob"]
            if value and existing_dob and value not in existing_dob:
                conflicts.append(ConflictItem(
                    field_name=f.field_name,
                    extracted_value=str(f.value),
                    existing_value=existing_dob,
                    conflict_type=ConflictType.DEMOGRAPHIC_MISMATCH,
                    severity=ConflictSeverity.HIGH,
                    message=f"DOB mismatch: extracted '{f.value}' vs existing '{existing_dob}'",
                    source_document=f.source_document,
                    recommendation="Verify patient identity.",
                ))

    return conflicts


# ── Lab value range checks ──────────────────────────────────────────────────

# Physiological reference ranges for common labs
_LAB_RANGES: Dict[str, Dict[str, float]] = {
    "hemoglobin": {"min": 7.0, "max": 20.0},
    "hgb": {"min": 7.0, "max": 20.0},
    "hematocrit": {"min": 20.0, "max": 60.0},
    "hct": {"min": 20.0, "max": 60.0},
    "wbc": {"min": 1.0, "max": 30.0},
    "platelets": {"min": 20.0, "max": 600.0},
    "glucose": {"min": 30.0, "max": 500.0},
    "creatinine": {"min": 0.2, "max": 15.0},
    "bun": {"min": 2.0, "max": 100.0},
    "sodium": {"min": 120.0, "max": 160.0},
    "potassium": {"min": 2.5, "max": 7.0},
    "calcium": {"min": 6.0, "max": 14.0},
    "hba1c": {"min": 3.0, "max": 15.0},
    "tsh": {"min": 0.01, "max": 100.0},
    "cholesterol": {"min": 80.0, "max": 400.0},
    "troponin": {"min": 0.0, "max": 50.0},
    "inr": {"min": 0.5, "max": 10.0},
}


def _check_lab_ranges(fields: List[ExtractedField]) -> List[ConflictItem]:
    """Flag lab values outside physiological ranges."""
    conflicts = []
    lab_fields = [f for f in fields if f.category == FieldCategory.LAB_RESULT]

    for f in lab_fields:
        test_name = f.field_name.lower()
        ref = _LAB_RANGES.get(test_name)
        if not ref:
            continue

        try:
            value = float(f.value)
        except (ValueError, TypeError):
            continue

        if value < ref["min"] or value > ref["max"]:
            severity = ConflictSeverity.HIGH if (
                value < ref["min"] * 0.7 or value > ref["max"] * 1.3
            ) else ConflictSeverity.MEDIUM

            conflicts.append(ConflictItem(
                field_name=f.field_name,
                extracted_value=str(f.value),
                existing_value=f"Expected range: {ref['min']}-{ref['max']}",
                conflict_type=ConflictType.VALUE_OUT_OF_RANGE,
                severity=severity,
                message=f"Lab value '{test_name}' = {value} is outside expected range ({ref['min']}-{ref['max']})",
                source_document=f.source_document,
                recommendation="Verify this value — may be an OCR error or requires clinical attention.",
            ))

    return conflicts


def _check_medication_duplicates(
    fields: List[ExtractedField],
    history: Dict[str, Any],
) -> List[ConflictItem]:
    """Detect duplicate medications between extracted and existing records."""
    conflicts = []
    existing_meds = history.get("medications", [])
    if not existing_meds:
        return conflicts

    existing_med_map = {}
    for m in existing_meds:
        if isinstance(m, dict) and m.get("name"):
            existing_med_map[m["name"].lower()] = m

    new_meds = [f for f in fields if f.category == FieldCategory.MEDICATION]

    for med in new_meds:
        med_name = str(med.value).lower().split()[0] if med.value else ""
        if med_name in existing_med_map:
            existing = existing_med_map[med_name]
            existing_dose = existing.get("dose", "unknown")
            new_dose = med.metadata.get("dose", "unknown")

            if new_dose != "unknown" and existing_dose != "unknown" and new_dose != existing_dose:
                conflicts.append(ConflictItem(
                    field_name=med.field_name,
                    extracted_value=str(med.value),
                    existing_value=f"{existing.get('name', med_name)} {existing_dose}",
                    conflict_type=ConflictType.DUPLICATE_MEDICATION,
                    severity=ConflictSeverity.MEDIUM,
                    message=f"Medication '{med_name}' already in record with different dosage: {existing_dose} vs {new_dose}",
                    source_document=med.source_document,
                    recommendation="Verify if dosage change is intended or an error.",
                ))

    return conflicts
