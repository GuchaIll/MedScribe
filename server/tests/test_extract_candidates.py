import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set environment variables before import
os.environ['HUGGINGFACE_API_KEY'] = 'test_token'
os.environ['LLM_MODEL'] = 'api'  # Use API mode to avoid loading local models
os.environ['GROQ_API_KEY'] = 'test_groq_key'  # For API client tests

# Mock heavy dependencies before importing
sys.modules['faster_whisper'] = Mock()
sys.modules['pyannote'] = Mock()
sys.modules['pyannote.audio'] = Mock()
sys.modules['transformers'] = Mock()

from app.agents.nodes import extract
from tests.helpers import make_test_context


def _base_state():
    return {
        "session_id": "sess_test",
        "patient_id": "pat_test",
        "doctor_id": "doc_test",
        "conversation_log": [],
        "inputs": {},
        "documents": [],
        "chunks": [],
        "candidate_facts": [],
        "structured_record": {},
        "validation_report": None,
        "conflict_report": None,
        "controls": {
            "attempts": {},
            "budget": {"max_total_llm_calls": 30, "llm_calls_used": 0},
        },
    }


class ExtractCandidatesTests(unittest.TestCase):
    
    def test_extraction_with_chunks(self):
        """Test extraction when chunks are provided"""
        # Mock LLM response
        with patch('app.agents.nodes.extract.LLMClient') as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = json.dumps({
                "facts": [
                    {
                        "fact_type": "allergy",
                        "value": {"substance": "Penicillin", "reaction": "rash"},
                        "confidence": 0.95,
                        "evidence_text": "Patient is allergic to Penicillin"
                    },
                    {
                        "fact_type": "medication",
                        "value": {"name": "Lisinopril", "dose": "10mg", "frequency": "daily"},
                        "confidence": 0.90,
                        "evidence_text": "Currently taking Lisinopril 10mg daily for hypertension"
                    },
                    {
                        "fact_type": "vital",
                        "value": {"type": "BP", "value": "120/80"},
                        "confidence": 0.95,
                        "evidence_text": "Blood pressure today is 120/80"
                    }
                ]
            })
            mock_llm.generate_response.return_value = mock_response
            mock_llm_class.return_value = mock_llm
            
            # Import after mocking
            from app.agents.nodes.extract import extract_candidates_node
            
            state = _base_state()
            state["chunks"] = [
                {
                    "chunk_id": "chunk_1",
                    "source": "transcript",
                    "source_id": "sess_test",
                    "start_time": 0.0,
                    "end_time": 10.0,
                    "text": "Patient is allergic to Penicillin. Currently taking Lisinopril 10mg daily for hypertension.",
                    "tags": ["Doctor"]
                },
                {
                    "chunk_id": "chunk_2",
                    "source": "transcript",
                    "source_id": "sess_test",
                    "start_time": 10.0,
                    "end_time": 20.0,
                    "text": "Blood pressure today is 120/80. Patient reports good compliance with medications.",
                    "tags": ["Doctor"]
                }
            ]
            
            ctx = make_test_context()
            new_state = extract_candidates_node(state, ctx)
            
            # Verify candidates were extracted
            candidates = new_state.get("candidate_facts", [])
            self.assertEqual(len(candidates), 3, "Should extract 3 candidates from mock response")
            
            # Verify all candidates have required fields
            for candidate in candidates:
                self.assertIn("fact_id", candidate)
                self.assertIn("type", candidate)
                self.assertIn("value", candidate)
                self.assertIn("confidence", candidate)
                self.assertIn("provenance", candidate)
                
                # Verify confidence is in valid range
                confidence = candidate["confidence"]
                self.assertIsInstance(confidence, (int, float))
                self.assertGreaterEqual(confidence, 0.0)
                self.assertLessEqual(confidence, 1.0)
                
                # Verify evidence spans exist
                provenance = candidate["provenance"]
                evidence = provenance.get("evidence", [])
                self.assertGreater(len(evidence), 0, "Each candidate must have at least one evidence span")
                
                # Verify evidence structure
                for ev in evidence:
                    self.assertIn("source", ev)
                    self.assertIn("snippet", ev)
                    self.assertIn("strength", ev)
            
            # Verify specific extracted entities
            fact_types = [c["type"] for c in candidates]
            self.assertIn("allergy", fact_types)
            self.assertIn("medication", fact_types)
            self.assertIn("vital", fact_types)
    
    def test_extraction_from_conversation_log_fallback(self):
        """Test extraction falls back to conversation_log when chunks not available"""
        with patch('app.agents.nodes.extract.LLMClient') as mock_llm_class:
            # Mock LLM response
            mock_llm = MagicMock()
            mock_response = json.dumps({
                "facts": [
                    {
                        "fact_type": "diagnosis",
                        "value": {"code": "E11", "description": "Type 2 diabetes mellitus"},
                        "confidence": 0.85,
                        "evidence_text": "Patient has diabetes"
                    }
                ]
            })
            mock_llm.generate_response.return_value = mock_response
            mock_llm_class.return_value = mock_llm
            
            from app.agents.nodes.extract import extract_candidates_node
            
            state = _base_state()
            state["conversation_log"] = [
                {
                    "timestamp": 1234567890,
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 5.0,
                            "speaker": "Doctor",
                            "raw_text": "Patient has diabetes.",
                            "cleaned_text": "Patient has diabetes.",
                            "uncertainties": [],
                            "confidence": "high"
                        }
                    ]
                }
            ]
            
            ctx = make_test_context()
            new_state = extract_candidates_node(state, ctx)
            
            # Should create candidates even without pre-chunked data
            candidates = new_state.get("candidate_facts", [])
            self.assertGreater(len(candidates), 0, "Should extract candidates from conversation log")
            self.assertEqual(candidates[0]["type"], "diagnosis")
    
    def test_budget_tracking(self):
        """Test that LLM calls are tracked against budget"""
        with patch('app.agents.nodes.extract.LLMClient') as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = json.dumps({"facts": []})
            mock_llm.generate_response.return_value = mock_response
            mock_llm_class.return_value = mock_llm
            
            from app.agents.nodes.extract import extract_candidates_node
            
            state = _base_state()
            state["chunks"] = [
                {
                    "chunk_id": "chunk_1",
                    "source": "transcript",
                    "source_id": "sess_test",
                    "text": "Patient taking aspirin 81mg daily.",
                    "tags": []
                }
            ]
            
            initial_calls = state["controls"]["budget"]["llm_calls_used"]
            ctx = make_test_context()
            new_state = extract_candidates_node(state, ctx)
            
            # Should have incremented LLM call counter
            final_calls = new_state["controls"]["budget"]["llm_calls_used"]
            self.assertGreater(final_calls, initial_calls, "Should track LLM usage")
    
    def test_canonicalization(self):
        """Test that drug names are canonicalized"""
        with patch('app.agents.nodes.extract.LLMClient') as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = json.dumps({
                "facts": [
                    {
                        "fact_type": "medication",
                        "value": {"name": "Lipitor"},
                        "confidence": 0.90,
                        "evidence_text": "Patient is on Lipitor for cholesterol"
                    }
                ]
            })
            mock_llm.generate_response.return_value = mock_response
            mock_llm_class.return_value = mock_llm
            
            from app.agents.nodes.extract import extract_candidates_node
            
            state = _base_state()
            state["chunks"] = [
                {
                    "chunk_id": "chunk_1",
                    "source": "transcript",
                    "source_id": "sess_test",
                    "text": "Patient is on Lipitor for cholesterol.",
                    "tags": []
                }
            ]
            
            ctx = make_test_context()
            new_state = extract_candidates_node(state, ctx)
            candidates = new_state.get("candidate_facts", [])
            
            # Look for medication candidates
            med_candidates = [c for c in candidates if c.get("type") == "medication"]
            self.assertGreater(len(med_candidates), 0, "Should have medication candidate")
            
            # Lipitor should be canonicalized to Atorvastatin
            med = med_candidates[0]
            name = med.get("value", {}).get("name", "").lower()
            self.assertIn("atorvastatin", name, "Lipitor should be canonicalized to Atorvastatin")
            self.assertTrue(med.get("normalized"), "Should be marked as normalized")
    
    def test_json_retry_on_failure(self):
        """Test that system retries on malformed JSON"""
        with patch('app.agents.nodes.extract.LLMClient') as mock_llm_class:
            mock_llm = MagicMock()
            # First call returns invalid JSON, second call succeeds
            mock_llm.generate_response.side_effect = [
                "This is not valid JSON",
                json.dumps({
                    "facts": [
                        {
                            "fact_type": "medication",
                            "value": {"name": "Aspirin"},
                            "confidence": 0.8,
                            "evidence_text": "taking aspirin"
                        }
                    ]
                })
            ]
            mock_llm_class.return_value = mock_llm
            
            from app.agents.nodes.extract import extract_candidates_node
            
            state = _base_state()
            state["chunks"] = [
                {
                    "chunk_id": "chunk_1",
                    "source": "transcript",
                    "source_id": "sess_test",
                    "text": "Patient taking aspirin 81mg daily.",
                    "tags": []
                }
            ]
            
            ctx = make_test_context()
            new_state = extract_candidates_node(state, ctx)
            
            # Should succeed after retry
            candidates = new_state.get("candidate_facts", [])
            self.assertGreater(len(candidates), 0, "Should extract after retry")
            
            # Verify LLM was called twice (once failed, once succeeded)
            self.assertEqual(mock_llm.generate_response.call_count, 2)


if __name__ == "__main__":
    unittest.main()


# ---------- DUPLICATE CODE REMOVED ----------
# The following duplicate test methods and second `if __name__` block were
# removed during the refactoring cleanup.  They were exact copies of the
# mocked tests above but without proper mock setup.
# ---------- END REMOVED BLOCK ----------
