"""
Unit tests for /api/records routes.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.routes.records import router

# Minimal app for isolated route testing
_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

SOAP_RECORD = {
    "patient": {
        "name": "Jane Doe",
        "mrn": "MRN99",
        "dob": "1985-06-15",
        "age": 38,
        "sex": "F"
    },
    "visit": {
        "date": "2024-02-15",
        "time": "09:00",
        "provider": "Dr. Adams",
        "type": "Office Visit"
    },
    "chief_complaint": "Headache for 2 days",
    "notes": {
        "subjective": "Patient reports throbbing headache.",
        "objective": "Alert, oriented x3. Neurological exam normal.",
        "assessment": "Tension headache.",
        "plan": "Rest, hydration, OTC analgesics."
    },
    "vital_signs": {
        "blood_pressure": "118/76",
        "heart_rate": "70",
        "temperature": "98.2°F",
        "respiratory_rate": "14",
        "oxygen_saturation": "99%"
    },
    "diagnoses": [{"description": "Tension headache", "code": "G44.2", "status": "active"}],
    "medications": [],
    "allergies": [{"substance": "Sulfa", "reaction": "Rash", "severity": "mild"}]
}


class TestListTemplates:
    def test_returns_four_templates(self):
        resp = client.get("/api/records/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        names = {t["name"] for t in data}
        assert names == {"soap", "discharge", "consultation", "progress"}

    def test_each_template_has_formats(self):
        resp = client.get("/api/records/templates")
        for t in resp.json():
            assert "html" in t["formats"]
            assert "pdf" in t["formats"]
            assert "text" in t["formats"]


class TestGenerateRecord:
    def test_generate_soap_html(self):
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "soap",
            "format": "html"
        })
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        assert "Jane Doe" in body
        assert "MRN99" in body

    def test_generate_plain_text(self):
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "soap",
            "format": "text"
        })
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "Jane Doe" in resp.text

    def test_generate_pdf_skips_when_weasyprint_missing(self):
        """PDF endpoint returns HTML when WeasyPrint is not installed."""
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "soap",
            "format": "pdf"
        })
        # Either real PDF or HTML fallback — must not error
        assert resp.status_code == 200
        assert resp.content  # non-empty

    def test_generate_with_clinical_suggestions(self):
        suggestions = {
            "allergy_alerts": [
                {
                    "severity": "critical",
                    "message": "Allergy alert",
                    "reaction": "Rash",
                    "allergy_severity": "mild",
                    "recommendation": "Avoid sulfa drugs"
                }
            ],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "critical"
        }
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "soap",
            "clinical_suggestions": suggestions,
            "format": "html"
        })
        assert resp.status_code == 200
        assert "ALLERGY ALERT" in resp.text or "allergy" in resp.text.lower()

    def test_unknown_template_returns_400(self):
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "nonexistent",
            "format": "html"
        })
        assert resp.status_code == 400
        assert "nonexistent" in resp.json()["detail"]

    def test_unknown_format_returns_400(self):
        resp = client.post("/api/records/generate", json={
            "record": SOAP_RECORD,
            "template": "soap",
            "format": "docx"
        })
        assert resp.status_code == 400

    def test_generate_all_templates(self):
        for template in ["soap", "discharge", "consultation", "progress"]:
            resp = client.post("/api/records/generate", json={
                "record": SOAP_RECORD,
                "template": template,
                "format": "html"
            })
            assert resp.status_code == 200, f"Template '{template}' failed: {resp.text}"


class TestPreviewRecord:
    def test_preview_returns_html(self):
        resp = client.post("/api/records/preview", json={
            "record": SOAP_RECORD,
            "template": "soap"
        })
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Jane Doe" in resp.text

    def test_preview_bad_template_returns_400(self):
        resp = client.post("/api/records/preview", json={
            "record": SOAP_RECORD,
            "template": "bad_template"
        })
        assert resp.status_code == 400
