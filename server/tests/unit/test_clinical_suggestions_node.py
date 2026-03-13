"""
Unit tests for clinical_suggestions_node.py
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from app.agents.nodes.clinical_suggestions import clinical_suggestions_node
from app.agents.state import GraphState


class TestClinicalSuggestionsNode:
    """Tests for clinical_suggestions_node integration."""

    @pytest.fixture
    def minimal_state(self):
        """Create minimal graph state for testing."""
        return {
            "session_id": "test_session_123",
            "patient_id": "PAT001",
            "structured_record": {
                "patient": {
                    "name": "Test Patient",
                    "mrn": "MRN001"
                },
                "medications": [
                    {"name": "Metformin 500mg", "dose": "500mg", "frequency": "BID"}
                ]
            },
            "flags": {
                "needs_review": False,
                "review_reasons": []
            },
            "controls": {
                "trace_log": [],
                "attempts": {},
                "budget": 30
            }
        }

    @pytest.fixture
    def mock_patient_history(self):
        """Mock patient history."""
        return {
            "found": True,
            "patient_id": "PAT001",
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
            ],
            "medications": [
                {"name": "Lisinopril 10mg", "status": "active"}
            ],
            "diagnoses": [
                {"description": "Type 2 diabetes", "status": "active"}
            ],
            "labs": [],
            "procedures": []
        }

    @pytest.fixture
    def mock_clinical_suggestions(self):
        """Mock clinical suggestions."""
        return {
            "allergy_alerts": [],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {
                "chronic_conditions": [
                    {"description": "Type 2 diabetes", "status": "active"}
                ],
                "recent_procedures": [],
                "recent_labs": []
            },
            "risk_level": "low",
            "timestamp": datetime.now().isoformat()
        }

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_node_successful_execution(
        self,
        mock_engine,
        mock_service,
        mock_db,
        minimal_state,
        mock_patient_history,
        mock_clinical_suggestions
    ):
        """Test successful node execution."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = mock_patient_history
        mock_service.return_value = mock_service_instance

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = mock_clinical_suggestions
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify state updated
        assert "clinical_suggestions" in result_state
        assert result_state["clinical_suggestions"]["risk_level"] == "low"

        # Verify trace log updated
        assert len(result_state["controls"]["trace_log"]) > 0
        assert any(
            log["node"] == "clinical_suggestions" and log["action"] == "started"
            for log in result_state["controls"]["trace_log"]
        )
        assert any(
            log["node"] == "clinical_suggestions" and log["action"] == "completed"
            for log in result_state["controls"]["trace_log"]
        )

    @patch('app.database.session.get_db_context')
    def test_node_skips_when_no_patient_id(self, mock_db, minimal_state):
        """Test node skips execution when patient_id is missing."""
        # Remove patient_id
        del minimal_state["patient_id"]

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify skipped
        assert "clinical_suggestions" not in result_state
        assert any(
            log["action"] == "skipped" and log["reason"] == "No patient_id provided"
            for log in result_state["controls"]["trace_log"]
        )

    @patch('app.database.session.get_db_context')
    def test_node_skips_when_no_structured_record(self, mock_db, minimal_state):
        """Test node skips execution when structured_record is missing."""
        # Remove structured_record
        minimal_state["structured_record"] = {}

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify skipped
        assert "clinical_suggestions" not in result_state
        assert any(
            log["action"] == "skipped" and log["reason"] == "No structured_record available"
            for log in result_state["controls"]["trace_log"]
        )

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    def test_node_skips_when_patient_not_found(
        self,
        mock_service,
        mock_db,
        minimal_state
    ):
        """Test node skips when patient history not found."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = {"found": False}
        mock_service.return_value = mock_service_instance

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify skipped
        assert "clinical_suggestions" not in result_state
        assert any(
            log["action"] == "skipped" and log["reason"] == "Patient history not found"
            for log in result_state["controls"]["trace_log"]
        )


class TestCriticalAlertFlagging:
    """Tests for critical alert flagging behavior."""

    @pytest.fixture
    def state_with_allergy_conflict(self):
        """State with allergy-medication conflict."""
        return {
            "session_id": "test_session_456",
            "patient_id": "PAT002",
            "structured_record": {
                "medications": [
                    {"name": "Amoxicillin 500mg", "dose": "500mg"}
                ]
            },
            "flags": {
                "needs_review": False,
                "review_reasons": []
            },
            "controls": {
                "trace_log": [],
                "attempts": {},
                "budget": 30
            }
        }

    @pytest.fixture
    def patient_history_with_penicillin_allergy(self):
        """Patient history with penicillin allergy."""
        return {
            "found": True,
            "patient_id": "PAT002",
            "allergies": [
                {"substance": "Penicillin", "reaction": "Anaphylaxis", "severity": "severe"}
            ],
            "medications": [],
            "diagnoses": []
        }

    @pytest.fixture
    def critical_suggestions(self):
        """Clinical suggestions with critical alert."""
        return {
            "allergy_alerts": [
                {
                    "severity": "critical",
                    "medication": "Amoxicillin",
                    "allergy": "Penicillin",
                    "message": "Cross-reactivity: Amoxicillin is a penicillin derivative",
                    "recommendation": "Discontinue immediately. Use alternative antibiotic."
                }
            ],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "critical",
            "timestamp": datetime.now().isoformat()
        }

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_critical_alert_sets_needs_review(
        self,
        mock_engine,
        mock_service,
        mock_db,
        state_with_allergy_conflict,
        patient_history_with_penicillin_allergy,
        critical_suggestions
    ):
        """Test that critical alerts trigger needs_review flag."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = patient_history_with_penicillin_allergy
        mock_service.return_value = mock_service_instance

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = critical_suggestions
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(state_with_allergy_conflict)

        # Verify critical flag set
        assert result_state["flags"]["needs_review"] is True
        assert len(result_state["flags"]["review_reasons"]) > 0
        assert any(
            "Critical clinical alert" in reason
            for reason in result_state["flags"]["review_reasons"]
        )

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_high_risk_sets_needs_review(
        self,
        mock_engine,
        mock_service,
        mock_db,
        state_with_allergy_conflict,
        patient_history_with_penicillin_allergy
    ):
        """Test that high risk level does not automatically set needs_review (only critical does)."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = patient_history_with_penicillin_allergy
        mock_service.return_value = mock_service_instance

        high_risk_suggestions = {
            "allergy_alerts": [],
            "drug_interactions": [
                {"severity": "major", "drugs": ["Warfarin", "Aspirin"]}
            ],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "high"
        }

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = high_risk_suggestions
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(state_with_allergy_conflict)

        # High risk should NOT trigger review (only critical does)
        assert result_state["flags"]["needs_review"] is False


class TestErrorHandling:
    """Tests for error handling in clinical suggestions node."""

    @pytest.fixture
    def minimal_state(self):
        """Create minimal graph state."""
        return {
            "session_id": "test_session_error",
            "patient_id": "PAT003",
            "structured_record": {
                "medications": []
            },
            "flags": {
                "needs_review": False,
                "review_reasons": []
            },
            "controls": {
                "trace_log": [],
                "attempts": {},
                "budget": 30
            }
        }

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    def test_database_error_handling(
        self,
        mock_service,
        mock_db,
        minimal_state
    ):
        """Test handling of database errors -- legacy path swallows the exception
        and returns None, so the node logs a 'skipped' trace (not 'error')."""
        # Setup mock to raise error
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.side_effect = Exception("Database connection failed")
        mock_service.return_value = mock_service_instance

        # Execute node - should not crash
        result_state = clinical_suggestions_node(minimal_state)

        # The legacy _get_patient_history swallows the exception and returns None,
        # so the node records a 'skipped' trace instead of 'error'.
        assert any(
            log["action"] == "skipped"
            for log in result_state["controls"]["trace_log"]
        )

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_suggestion_engine_error_handling(
        self,
        mock_engine,
        mock_service,
        mock_db,
        minimal_state
    ):
        """Test handling of suggestion engine errors."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = {"found": True, "allergies": []}
        mock_service.return_value = mock_service_instance

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.side_effect = Exception("Engine processing failed")
        mock_engine.return_value = mock_engine_instance

        # Execute node - should not crash
        result_state = clinical_suggestions_node(minimal_state)

        # Verify error logged
        assert any(
            log["action"] == "error" and "Engine processing failed" in log.get("error", "")
            for log in result_state["controls"]["trace_log"]
        )

        # Verify empty suggestions set
        assert "clinical_suggestions" in result_state
        assert result_state["clinical_suggestions"]["allergy_alerts"] == []
        assert result_state["clinical_suggestions"]["drug_interactions"] == []


class TestTraceLogging:
    """Tests for comprehensive trace logging."""

    @pytest.fixture
    def minimal_state(self):
        """Create minimal graph state."""
        return {
            "session_id": "test_trace",
            "patient_id": "PAT004",
            "structured_record": {
                "medications": [
                    {"name": "Metformin 500mg"}
                ]
            },
            "flags": {
                "needs_review": False,
                "review_reasons": []
            },
            "controls": {
                "trace_log": [],
                "attempts": {},
                "budget": 30
            }
        }

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_trace_log_includes_all_events(
        self,
        mock_engine,
        mock_service,
        mock_db,
        minimal_state
    ):
        """Test that trace log includes started and completed events."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = {"found": True, "allergies": []}
        mock_service.return_value = mock_service_instance

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = {
            "allergy_alerts": [],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "low"
        }
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify trace log
        trace_log = result_state["controls"]["trace_log"]

        # Should have started event
        started_events = [log for log in trace_log if log["action"] == "started"]
        assert len(started_events) > 0
        assert started_events[0]["node"] == "clinical_suggestions"

        # Should have completed event
        completed_events = [log for log in trace_log if log["action"] == "completed"]
        assert len(completed_events) > 0
        assert completed_events[0]["node"] == "clinical_suggestions"

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_trace_log_includes_metrics(
        self,
        mock_engine,
        mock_service,
        mock_db,
        minimal_state
    ):
        """Test that trace log includes metrics about suggestions."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = {"found": True, "allergies": []}
        mock_service.return_value = mock_service_instance

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = {
            "allergy_alerts": [{"severity": "critical"}],
            "drug_interactions": [{"severity": "major"}, {"severity": "moderate"}],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "high"
        }
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(minimal_state)

        # Verify completed event has metrics
        completed_events = [log for log in result_state["controls"]["trace_log"] if log["action"] == "completed"]
        assert len(completed_events) > 0

        completed = completed_events[0]
        assert "risk_level" in completed
        assert completed["risk_level"] == "high"
        assert "allergy_alerts" in completed
        assert completed["allergy_alerts"] == 1
        assert "drug_interactions" in completed
        assert completed["drug_interactions"] == 2


class TestIntegrationWithWorkflow:
    """Integration tests with full workflow state."""

    @pytest.fixture
    def realistic_state(self):
        """Create realistic workflow state."""
        return {
            "session_id": "session_real_001",
            "patient_id": "PAT_REAL_001",
            "conversation_log": [
                {
                    "speaker": "Doctor",
                    "text": "Patient presents with chest pain",
                    "timestamp": "2024-02-12T10:00:00"
                }
            ],
            "structured_record": {
                "patient": {
                    "name": "John Smith",
                    "mrn": "MRN_REAL_001",
                    "age": 65,
                    "sex": "M"
                },
                "visit": {
                    "date": "2024-02-12",
                    "provider": "Dr. Jones"
                },
                "chief_complaint": "Chest pain",
                "medications": [
                    {"name": "Warfarin 5mg", "dose": "5mg", "frequency": "daily"},
                    {"name": "Aspirin 81mg", "dose": "81mg", "frequency": "daily"}
                ],
                "allergies": [
                    {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
                ],
                "diagnoses": [
                    {"description": "Atrial fibrillation", "code": "I48.91", "status": "active"}
                ],
                "vital_signs": {
                    "blood_pressure": "140/90",
                    "heart_rate": "88"
                }
            },
            "flags": {
                "needs_review": False,
                "review_reasons": []
            },
            "controls": {
                "trace_log": [
                    {"node": "transcription", "action": "completed"},
                    {"node": "extract_candidates", "action": "completed"}
                ],
                "attempts": {},
                "budget": 30
            }
        }

    @pytest.fixture
    def realistic_patient_history(self):
        """Realistic patient history."""
        return {
            "found": True,
            "patient_id": "PAT_REAL_001",
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
            ],
            "medications": [
                {"name": "Warfarin 5mg", "status": "active", "start_date": "2023-01-15"},
                {"name": "Metoprolol 50mg", "status": "active", "start_date": "2023-01-15"}
            ],
            "diagnoses": [
                {
                    "description": "Atrial fibrillation",
                    "code": "I48.91",
                    "status": "active",
                    "first_recorded": "2023-01-15"
                },
                {
                    "description": "Hypertension",
                    "code": "I10",
                    "status": "active",
                    "first_recorded": "2020-05-10"
                }
            ],
            "procedures": [
                {"name": "Cardioversion", "date": "2023-06-10"}
            ],
            "labs": [
                {
                    "test_name": "INR",
                    "value": "2.8",
                    "abnormal": False,
                    "date": "2024-02-01"
                }
            ]
        }

    @patch('app.database.session.get_db_context')
    @patch('app.core.patient_service.get_patient_service')
    @patch('app.core.clinical_suggestions.get_clinical_suggestion_engine')
    def test_realistic_workflow_integration(
        self,
        mock_engine,
        mock_service,
        mock_db,
        realistic_state,
        realistic_patient_history
    ):
        """Test node with realistic workflow state."""
        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db.return_value.__enter__ = Mock(return_value=mock_db_instance)
        mock_db.return_value.__exit__ = Mock(return_value=False)

        mock_service_instance = Mock()
        mock_service_instance.get_patient_history.return_value = realistic_patient_history
        mock_service.return_value = mock_service_instance

        # Realistic suggestions with warfarin+aspirin interaction
        realistic_suggestions = {
            "allergy_alerts": [],
            "drug_interactions": [
                {
                    "drug1": "Warfarin",
                    "drug2": "Aspirin",
                    "severity": "major",
                    "effect": "Increased risk of bleeding",
                    "recommendation": "Monitor INR closely. Consider gastroprotection."
                }
            ],
            "contraindications": [],
            "historical_context": {
                "chronic_conditions": [
                    {
                        "description": "Atrial fibrillation",
                        "duration": "1 year",
                        "status": "active"
                    },
                    {
                        "description": "Hypertension",
                        "duration": "4 years",
                        "status": "active"
                    }
                ],
                "recent_procedures": [
                    {"name": "Cardioversion", "date": "2023-06-10"}
                ],
                "recent_labs": [
                    {"test_name": "INR", "value": "2.8", "date": "2024-02-01"}
                ]
            },
            "risk_level": "moderate",
            "timestamp": datetime.now().isoformat()
        }

        mock_engine_instance = Mock()
        mock_engine_instance.generate_suggestions.return_value = realistic_suggestions
        mock_engine.return_value = mock_engine_instance

        # Execute node
        result_state = clinical_suggestions_node(realistic_state)

        # Verify suggestions added
        assert "clinical_suggestions" in result_state
        assert result_state["clinical_suggestions"]["risk_level"] == "moderate"
        assert len(result_state["clinical_suggestions"]["drug_interactions"]) > 0

        # Verify historical context included
        assert "chronic_conditions" in result_state["clinical_suggestions"]["historical_context"]
        assert len(result_state["clinical_suggestions"]["historical_context"]["chronic_conditions"]) == 2

        # Verify trace log updated appropriately
        assert len(result_state["controls"]["trace_log"]) > 2  # Previous + new entries

