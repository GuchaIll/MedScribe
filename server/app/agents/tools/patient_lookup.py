"""
Patient Lookup Tool — database-backed patient history retrieval.

Wraps PatientService so agent nodes can access patient data without
managing database sessions themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from app.core.patient_service import PatientService


class PatientLookupTool:
    """
    Tool for retrieving patient history within agent nodes.

    Requires a ``PatientService`` (which in turn holds a DB session).
    Prefer injecting via AgentContext rather than constructing directly.
    """

    def __init__(self, patient_service: PatientService | None = None):
        self._service = patient_service

    @property
    def service(self) -> PatientService:
        if self._service is None:
            raise RuntimeError(
                "PatientLookupTool requires a PatientService. "
                "Inject one via AgentContext.patient_service."
            )
        return self._service

    def get_history(self, patient_id: str) -> Dict[str, Any]:
        """
        Get aggregated patient history.

        Returns:
            Dict with keys: found, patient_info, medications, allergies,
            diagnoses, labs, procedures, etc.
        """
        return self.service.get_patient_history(patient_id)

    def get_allergies(self, patient_id: str) -> list:
        """Get patient allergies only."""
        history = self.get_history(patient_id)
        return history.get("allergies", [])

    def get_medications(self, patient_id: str) -> list:
        """Get patient active medications."""
        history = self.get_history(patient_id)
        return history.get("medications", [])

    def exists(self, patient_id: str) -> bool:
        """Check if patient exists in the database."""
        history = self.get_history(patient_id)
        return history.get("found", False)
