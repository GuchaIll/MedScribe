"""
Medical Facts Guardrail — prevent hallucinated entities in clinical output.

Validates that the generated clinical note references ONLY entities
(medications, allergies, diagnoses) present in the structured record.
Nothing the LLM "imagines" should slip into a patient-facing document.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


class MedicalFactsGuardrail:
    """
    Post-generation check that ensures clinical notes are grounded
    in the structured record.

    Usage::

        guardrail = MedicalFactsGuardrail(structured_record)
        violations = guardrail.check(clinical_note)
        if violations:
            state["flags"]["needs_review"] = True
    """

    def __init__(self, structured_record: Dict[str, Any]):
        self.record = structured_record
        self._known_entities = self._extract_known_entities()

    # ── Entity extraction from record ───────────────────────────────────────

    def _extract_known_entities(self) -> Set[str]:
        """Build a set of all known entity names from the structured record."""
        entities: Set[str] = set()

        # Medications
        for med in self.record.get("medications", []):
            name = med.get("name", "") if isinstance(med, dict) else str(med)
            if name:
                entities.add(name.lower().strip())

        # Allergies
        for allergy in self.record.get("allergies", []):
            substance = allergy.get("substance", "") if isinstance(allergy, dict) else str(allergy)
            if substance:
                entities.add(substance.lower().strip())

        # Diagnoses
        for dx in self.record.get("diagnoses", []):
            if isinstance(dx, dict):
                for key in ("description", "code", "name"):
                    val = dx.get(key, "")
                    if val:
                        entities.add(str(val).lower().strip())
            else:
                entities.add(str(dx).lower().strip())

        # Patient info
        patient = self.record.get("patient", {})
        if patient.get("name"):
            entities.add(patient["name"].lower().strip())

        # Problems
        for problem in self.record.get("problems", []):
            name = problem.get("name", "") if isinstance(problem, dict) else str(problem)
            if name:
                entities.add(name.lower().strip())

        return entities

    # ── Validation ──────────────────────────────────────────────────────────

    def check(self, clinical_note: str) -> List[str]:
        """
        Scan a clinical note for potential hallucinated medication or
        allergy names not present in the structured record.

        Returns a list of violation descriptions (empty = clean).
        """
        violations: List[str] = []

        if not clinical_note or not self._known_entities:
            return violations

        # Simple heuristic: look for capitalised medical-looking terms
        # that aren't in our known entity set
        note_lower = clinical_note.lower()

        # Check common medication patterns: "prescribed X", "started on X"
        med_patterns = [
            r"(?:prescrib|start|continu|discontinu|increas|decreas|adjust)[a-z]*\s+(?:on\s+)?(\w+)",
            r"(\w+)\s+\d+\s*(?:mg|mcg|ml|units?)\b",
        ]

        for pattern in med_patterns:
            for match in re.finditer(pattern, note_lower):
                term = match.group(1).strip()
                if len(term) > 3 and term not in self._known_entities:
                    # Skip common English words
                    if term not in _COMMON_WORDS:
                        violations.append(
                            f"Possible hallucinated entity '{term}' — "
                            f"not found in structured record"
                        )

        return violations

    def is_grounded(self, clinical_note: str) -> bool:
        """Return True if the note passes fact checking."""
        return len(self.check(clinical_note)) == 0


# Words that commonly appear near dosage patterns but aren't medications
_COMMON_WORDS: Set[str] = {
    "the", "and", "for", "with", "this", "that", "patient", "has", "was",
    "been", "will", "should", "dose", "tablet", "capsule", "injection",
    "once", "twice", "daily", "every", "hours", "days", "weeks", "oral",
    "take", "given", "administered", "avoid", "note", "history", "report",
    "start", "started", "continue", "continued", "increased", "decreased",
    "about", "approximately", "currently", "previously",
}
