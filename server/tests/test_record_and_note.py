import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set environment variables and mock dependencies before import
os.environ['HUGGINGFACE_API_KEY'] = 'test_token'
os.environ['LLM_MODEL'] = 'api'
os.environ['GROQ_API_KEY'] = 'test_groq_key'

sys.modules['faster_whisper'] = Mock()
sys.modules['pyannote'] = Mock()
sys.modules['pyannote.audio'] = Mock()
sys.modules['transformers'] = Mock()

from app.agents.nodes.fill_record import fill_structured_record_node
from app.agents.nodes.generate_note import generate_note_node
from tests.helpers import make_test_context


def _base_state():
    return {
        "session_id": "sess_test",
        "patient_id": "pat_test",
        "doctor_id": "doc_test",
        "inputs": {},
        "documents": [],
        "chunks": [],
        "candidate_facts": [],
        "structured_record": {},
        "provenance": [],
        "validation_report": {},
        "conflict_report": {},
        "clinical_note": None,
        "controls": {
            "attempts": {},
            "budget": {"max_total_llm_calls": 30, "llm_calls_used": 0},
        },
    }


class FillStructuredRecordTests(unittest.TestCase):
    
    def test_fills_patient_demographics(self):
        """Test that patient demographics are correctly mapped"""
        state = _base_state()
        state["candidate_facts"] = [
            {
                "fact_id": "f1",
                "fact_type": "patient_name",
                "value": "John Doe",
                "confidence": 0.95,
                "evidence": [{"source": "transcript", "snippet": "patient John Doe", "strength": 0.95}]
            },
            {
                "fact_id": "f2",
                "fact_type": "patient_dob",
                "value": "1980-05-15",
                "confidence": 0.90,
                "evidence": [{"source": "transcript", "snippet": "born May 15, 1980", "strength": 0.90}]
            },
            {
                "fact_id": "f3",
                "fact_type": "patient_age",
                "value": 43,
                "confidence": 0.85,
                "evidence": [{"source": "transcript", "snippet": "43 years old", "strength": 0.85}]
            }
        ]
        
        new_state = fill_structured_record_node(state)
        
        record = new_state["structured_record"]
        self.assertEqual(record["patient"]["name"], "John Doe")
        self.assertEqual(record["patient"]["dob"], "1980-05-15")
        self.assertEqual(record["patient"]["age"], 43)
        
        # Check provenance was created
        provenance = new_state["provenance"]
        self.assertEqual(len(provenance), 3)
        self.assertTrue(any(p["field_path"] == "patient.name" for p in provenance))
    
    def test_appends_medications_with_deduplication(self):
        """Test that duplicate medications are merged by preferring higher confidence"""
        state = _base_state()
        state["candidate_facts"] = [
            {
                "fact_id": "f1",
                "fact_type": "medication",
                "value": {"name": "Lisinopril", "dose": "10mg"},
                "confidence": 0.85,
                "evidence": [{"source": "transcript", "snippet": "Lisinopril 10mg", "strength": 0.85}]
            },
            {
                "fact_id": "f2",
                "fact_type": "medication",
                "value": {"name": "Lisinopril", "dose": "10mg", "frequency": "daily"},
                "confidence": 0.95,  # Higher confidence
                "evidence": [{"source": "document", "snippet": "Lisinopril 10mg daily", "strength": 0.95}]
            },
            {
                "fact_id": "f3",
                "fact_type": "medication",
                "value": {"name": "Aspirin", "dose": "81mg"},
                "confidence": 0.90,
                "evidence": [{"source": "transcript", "snippet": "Aspirin 81mg", "strength": 0.90}]
            }
        ]
        
        new_state = fill_structured_record_node(state)
        
        record = new_state["structured_record"]
        medications = record["medications"]
        
        # Should have 2 medications (Lisinopril merged, Aspirin separate)
        self.assertEqual(len(medications), 2)
        
        # Find Lisinopril
        lisinopril = next((m for m in medications if m["name"] == "Lisinopril"), None)
        self.assertIsNotNone(lisinopril)
        self.assertEqual(lisinopril["dose"], "10mg")
        self.assertEqual(lisinopril["frequency"], "daily")
        self.assertEqual(lisinopril["confidence"], 0.95)  # Higher confidence won
    
    def test_skips_candidates_without_evidence(self):
        """Test that candidates without evidence are not included"""
        state = _base_state()
        state["candidate_facts"] = [
            {
                "fact_id": "f1",
                "fact_type": "allergy",
                "value": {"substance": "Penicillin"},
                "confidence": 0.95,
                "evidence": [{"source": "transcript", "snippet": "allergic to Penicillin", "strength": 0.95}]
            },
            {
                "fact_id": "f2",
                "fact_type": "allergy",
                "value": {"substance": "Sulfa"},
                "confidence": 0.80,
                "evidence": []  # No evidence - should be skipped
            }
        ]
        
        new_state = fill_structured_record_node(state)
        
        record = new_state["structured_record"]
        allergies = record["allergies"]
        
        # Should only have 1 allergy (the one with evidence)
        self.assertEqual(len(allergies), 1)
        self.assertEqual(allergies[0]["substance"], "Penicillin")
    
    def test_builds_provenance_for_all_fields(self):
        """Test that provenance is tracked for each field"""
        state = _base_state()
        state["candidate_facts"] = [
            {
                "fact_id": "f1",
                "fact_type": "diagnosis",
                "value": {"code": "I10", "description": "Essential hypertension"},
                "confidence": 0.90,
                "evidence": [{"source": "transcript", "snippet": "hypertension", "strength": 0.90}]
            },
            {
                "fact_id": "f2",
                "fact_type": "vital",
                "value": {"type": "BP", "value": "140/90"},
                "confidence": 0.95,
                "evidence": [{"source": "transcript", "snippet": "BP 140/90", "strength": 0.95}]
            }
        ]
        
        new_state = fill_structured_record_node(state)
        
        provenance = new_state["provenance"]
        self.assertEqual(len(provenance), 2)
        
        # Check provenance structure
        for prov in provenance:
            self.assertIn("field_path", prov)
            self.assertIn("evidence", prov)
            self.assertIn("confidence", prov)
            self.assertGreater(len(prov["evidence"]), 0)


class GenerateNoteTests(unittest.TestCase):
    
    def test_generates_template_note_with_basic_data(self):
        """Test template-based note generation (no LLM)"""
        state = _base_state()
        state["structured_record"] = {
            "patient": {
                "name": "Jane Smith",
                "dob": "1975-08-20",
                "age": 48,
                "sex": "Female"
            },
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "confidence": 0.95}
            ],
            "medications": [
                {"name": "Metformin", "dose": "500mg", "frequency": "twice daily", "confidence": 0.90}
            ],
            "diagnoses": [
                {"code": "E11.9", "description": "Type 2 diabetes mellitus", "confidence": 0.92}
            ],
            "vitals": [
                {"type": "BP", "value": "130/85", "unit": "mmHg"}
            ],
            "labs": [],
            "procedures": [],
            "followups": [],
            "problems": [],
            "notes": {}
        }
        
        # Exhaust budget to force template generation
        state["controls"]["budget"]["llm_calls_used"] = 30
        
        new_state = generate_note_node(state, make_test_context())
        
        note = new_state["clinical_note"]
        self.assertIsNotNone(note)
        self.assertIn("Jane Smith", note)
        self.assertIn("Penicillin", note)
        self.assertIn("Metformin", note)
        self.assertIn("Type 2 diabetes", note)
        self.assertIn("SUBJECTIVE", note)
        self.assertIn("OBJECTIVE", note)
        self.assertIn("ASSESSMENT", note)
        self.assertIn("PLAN", note)
    
    def test_generates_llm_note_when_budget_available(self):
        """Test LLM-based note generation"""
        with patch('app.agents.nodes.generate_note.LLMClient') as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_response.return_value = """SUBJECTIVE
Patient reports well-controlled diabetes with good medication compliance.

OBJECTIVE
Vitals: BP 130/85 mmHg
No acute distress noted.

ASSESSMENT
Type 2 diabetes mellitus (E11.9) - stable

PLAN
Continue Metformin 500mg twice daily
Follow up in 3 months"""
            mock_llm_class.return_value = mock_llm
            
            state = _base_state()
            state["structured_record"] = {
                "patient": {"name": "Test Patient", "dob": "1980-01-01"},
                "allergies": [],
                "medications": [{"name": "Metformin", "dose": "500mg"}],
                "diagnoses": [{"code": "E11.9"}],
                "vitals": [{"type": "BP", "value": "130/85"}],
                "labs": [],
                "procedures": [],
                "followups": [],
                "problems": [],
                "notes": {}
            }
            
            new_state = generate_note_node(state, make_test_context())
            
            note = new_state["clinical_note"]
            self.assertIn("SUBJECTIVE", note)
            self.assertIn("Metformin", note)
            
            # Verify LLM was called
            self.assertEqual(mock_llm.generate_response.call_count, 1)
            
            # Verify budget was updated
            self.assertEqual(new_state["controls"]["budget"]["llm_calls_used"], 1)
    
    def test_includes_warnings_for_validation_issues(self):
        """Test that validation warnings are included in note"""
        state = _base_state()
        state["structured_record"] = {
            "patient": {"name": "Test", "dob": "1990-01-01"},
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
        state["validation_report"] = {
            "schema_errors": ["Missing required field: patient.sex"],
            "needs_review": True
        }
        state["conflict_report"] = {
            "conflicts": [
                {"conflict_id": "c1", "description": "Age mismatch"}
            ]
        }
        
        # Force template generation
        state["controls"]["budget"]["llm_calls_used"] = 30
        
        new_state = generate_note_node(state, make_test_context())
        
        note = new_state["clinical_note"]
        self.assertIn("WARNINGS", note)
        self.assertIn("Validation Issues", note)
        self.assertIn("Conflicts Detected", note)
        self.assertIn("requires clinical review", note)
    
    def test_handles_empty_record_gracefully(self):
        """Test that node handles missing data gracefully"""
        state = _base_state()
        state["structured_record"] = {}
        
        new_state = generate_note_node(state, make_test_context())
        
        note = new_state["clinical_note"]
        self.assertIn("Unable to generate note", note)


if __name__ == "__main__":
    unittest.main()
