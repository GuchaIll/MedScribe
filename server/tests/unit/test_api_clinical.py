"""
Unit tests for /api/clinical routes.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.routes.clinical import router

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

MEDS_WARFARIN_ASPIRIN = [
    {"name": "Warfarin 5mg", "dose": "5mg", "frequency": "daily"},
    {"name": "Aspirin 81mg", "dose": "81mg", "frequency": "daily"},
]

ALLERGIES_PENICILLIN = [
    {"substance": "Penicillin", "reaction": "Anaphylaxis", "severity": "severe"}
]


class TestClinicalSuggestions:
    def test_basic_suggestions(self):
        resp = client.post("/api/clinical/suggestions", json={
            "current_record": {
                "patient": {"name": "Test", "age": 50, "sex": "M"},
                "medications": MEDS_WARFARIN_ASPIRIN,
                "diagnoses": [],
                "allergies": []
            },
            "patient_history": {
                "found": True,
                "allergies": [],
                "medications": [],
                "diagnoses": [],
                "labs": []
            }
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "allergy_alerts" in data
        assert "drug_interactions" in data
        assert "risk_level" in data

    def test_allergy_conflict_detected(self):
        resp = client.post("/api/clinical/suggestions", json={
            "current_record": {
                "patient": {"name": "Test", "age": 40, "sex": "F"},
                "medications": [{"name": "Amoxicillin 500mg"}],
                "diagnoses": [],
                "allergies": []
            },
            "patient_history": {
                "found": True,
                "allergies": ALLERGIES_PENICILLIN,
                "medications": [],
                "diagnoses": [],
                "labs": []
            }
        })
        assert resp.status_code == 200
        data = resp.json()
        # Amoxicillin is a penicillin-class drug — should trigger alert
        assert len(data["allergy_alerts"]) > 0

    def test_no_history_uses_record_allergies(self):
        """Without explicit patient_history, allergies from the record itself are used."""
        resp = client.post("/api/clinical/suggestions", json={
            "current_record": {
                "medications": [{"name": "Amoxicillin 500mg"}],
                "diagnoses": [],
                "allergies": ALLERGIES_PENICILLIN
            }
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "allergy_alerts" in data

    def test_response_has_risk_level(self):
        resp = client.post("/api/clinical/suggestions", json={
            "current_record": {
                "medications": [],
                "diagnoses": [],
                "allergies": []
            }
        })
        assert resp.status_code == 200
        assert resp.json()["risk_level"] in ("low", "moderate", "high", "critical", "unknown")

    def test_drug_interaction_detected(self):
        resp = client.post("/api/clinical/suggestions", json={
            "current_record": {
                "medications": MEDS_WARFARIN_ASPIRIN,
                "diagnoses": [],
                "allergies": []
            },
            "patient_history": {
                "found": True,
                "allergies": [],
                "medications": [],
                "diagnoses": [],
                "labs": []
            }
        })
        assert resp.status_code == 200
        data = resp.json()
        # Warfarin + Aspirin is a known interaction
        assert len(data["drug_interactions"]) > 0


class TestCheckAllergies:
    def test_conflict_detected(self):
        resp = client.post("/api/clinical/check-allergies", json={
            "medications": [{"name": "Amoxicillin 500mg"}],
            "allergies": ALLERGIES_PENICILLIN
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "allergy_alerts" in data
        assert "risk_level" in data
        assert len(data["allergy_alerts"]) > 0

    def test_no_conflict(self):
        resp = client.post("/api/clinical/check-allergies", json={
            "medications": [{"name": "Metformin 500mg"}],
            "allergies": ALLERGIES_PENICILLIN
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["allergy_alerts"]) == 0

    def test_empty_lists(self):
        resp = client.post("/api/clinical/check-allergies", json={
            "medications": [],
            "allergies": []
        })
        assert resp.status_code == 200
        assert resp.json()["risk_level"] == "low"


class TestCheckInteractions:
    def test_interaction_detected(self):
        resp = client.post("/api/clinical/check-interactions", json={
            "medications": MEDS_WARFARIN_ASPIRIN
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "drug_interactions" in data
        assert len(data["drug_interactions"]) > 0

    def test_no_interaction(self):
        resp = client.post("/api/clinical/check-interactions", json={
            "medications": [
                {"name": "Metformin 500mg"},
                {"name": "Vitamin D 1000IU"}
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["drug_interactions"]) == 0

    def test_single_medication(self):
        resp = client.post("/api/clinical/check-interactions", json={
            "medications": [{"name": "Lisinopril 10mg"}]
        })
        assert resp.status_code == 200
        assert resp.json()["drug_interactions"] == []
