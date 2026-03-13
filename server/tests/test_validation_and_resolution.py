import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.nodes.validate import validate_and_score_node
from app.agents.nodes.conflicts import conflict_resolution_node
from tests.helpers import make_test_context


def _base_state():
    return {
        "session_id": "sess_test",
        "patient_id": "pat_test",
        "doctor_id": "doc_test",
        "conversation_log": [],
        "new_segments": [],
        "session_summary": None,
        "patient_record_fields": None,
        "message": None,
        "flags": {},
        "inputs": {},
        "documents": [],
        "chunks": [],
        "candidate_facts": [],
        "evidence_map": {},
        "structured_record": {},
        "validation_report": None,
        "conflict_report": None,
        "clinical_note": None,
        "controls": {
            "attempts": {},
            "budget": {},
            "trace_log": [],
        },
    }


class ValidationContractTests(unittest.TestCase):
    def test_validation_reports_missing_and_schema_errors(self):
        state = _base_state()
        state["structured_record"] = {
            "patient": {
                "name": "",
                "dob": "not-a-date",
            },
            "visit": {
                "date": "2025-01-01",
            },
        }

        new_state = validate_and_score_node(state, make_test_context())
        report = new_state["validation_report"]

        self.assertIn("patient.name", report["missing_fields"])
        self.assertIn("patient.dob must be ISO-8601 date", report["schema_errors"])


class ConflictResolutionTests(unittest.TestCase):
    def test_conflict_resolution_merges_diagnosis_entries(self):
        state = _base_state()
        state["structured_record"] = {"diagnoses": []}
        state["candidate_facts"] = [
            {
                "fact_id": "f1",
                "type": "diagnosis_code",
                "value": "I10",
                "provenance": {},
                "confidence": 0.9,
            },
            {
                "fact_id": "f2",
                "type": "diagnosis_description",
                "value": {"code": "I10", "description": "Primary hypertension"},
                "provenance": {},
                "confidence": 0.8,
            },
        ]

        new_state = conflict_resolution_node(state, make_test_context())
        diagnoses = new_state["structured_record"]["diagnoses"]

        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["code"], "I10")
        self.assertEqual(diagnoses[0]["description"], "Primary hypertension")


if __name__ == "__main__":
    unittest.main()
