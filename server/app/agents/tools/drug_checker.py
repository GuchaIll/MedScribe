"""
Drug Checker Tool — wraps ClinicalSuggestionEngine for agent use.

Provides a narrow interface for checking drug interactions and allergy
conflicts without exposing the full engine API to every node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set

if TYPE_CHECKING:
    from app.core.clinical_suggestions import ClinicalSuggestionEngine

#TODO: In the future, this tool could be expanded to include dosage checks, contraindications, and more sophisticated NLP-based drug extraction. For now, it focuses on core safety checks relevant to medication management.
# Default drug vocabulary for keyword-based extraction
KNOWN_DRUGS: Set[str] = {
    "warfarin", "aspirin", "amoxicillin", "penicillin", "lisinopril",
    "metformin", "ibuprofen", "acetaminophen", "metoprolol", "atorvastatin",
    "clopidogrel", "digoxin", "fluconazole", "rifampin", "carbamazepine",
    "simvastatin", "clarithromycin", "erythromycin", "naproxen", "diclofenac",
    "heparin", "sertraline", "fluoxetine", "omeprazole",
}


class DrugCheckerTool:
    """
    Lightweight tool for agent nodes to check drug safety.

    Wraps ``ClinicalSuggestionEngine`` and exposes only what nodes need.
    """

    def __init__(self, engine: ClinicalSuggestionEngine | None = None):
        self._engine = engine

    @property
    def engine(self) -> ClinicalSuggestionEngine:
        if self._engine is None:
            from app.core.clinical_suggestions import get_clinical_suggestion_engine
            self._engine = get_clinical_suggestion_engine()
        return self._engine

    def check_interactions(
        self,
        medications: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check drug-drug interactions for a list of medications."""
        record = {"medications": medications, "diagnoses": []}
        history = {
            "found": True,
            "allergies": [],
            "medications": [],
            "diagnoses": [],
            "labs": [],
        }
        suggestions = self.engine.generate_suggestions(
            current_record=record,
            patient_history=history,
        )
        return {
            "drug_interactions": suggestions.get("drug_interactions", []),
            "risk_level": suggestions.get("risk_level", "low"),
        }

    def check_allergy_conflicts(
        self,
        medications: List[Dict[str, Any]],
        allergies: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check medication-allergy conflicts."""
        record = {"medications": medications, "diagnoses": []}
        history = {
            "found": True,
            "allergies": allergies,
            "medications": [],
            "diagnoses": [],
            "labs": [],
        }
        suggestions = self.engine.generate_suggestions(
            current_record=record,
            patient_history=history,
        )
        return {
            "allergy_alerts": suggestions.get("allergy_alerts", []),
            "risk_level": suggestions.get("risk_level", "low"),
        }

    def extract_drug_names(self, text: str) -> List[str]:
        """Extract known drug names from free text."""
        text_lower = text.lower()
        return [drug for drug in KNOWN_DRUGS if drug in text_lower]
