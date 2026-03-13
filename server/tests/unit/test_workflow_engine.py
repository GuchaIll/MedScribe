"""
Unit tests for workflow_engine.py (simplified version)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from app.agents.state import GraphState


@pytest.mark.unit
class TestWorkflowEngineBasic:
    """Basic tests for WorkflowEngine (with mocked dependencies)."""

    @patch('app.core.workflow_engine.create_default_context')
    @patch('app.core.workflow_engine.build_graph')
    def test_import_workflow_engine(self, mock_build_graph, mock_create_ctx):
        """Test that WorkflowEngine can be imported and instantiated."""
        from app.core.workflow_engine import WorkflowEngine

        # Mock the dependencies
        mock_create_ctx.return_value = Mock()
        mock_build_graph.return_value = Mock()

        # Should be able to create instance
        engine = WorkflowEngine(enable_checkpointing=False, enable_interrupts=False)
        assert engine is not None

    @patch('app.core.workflow_engine.create_default_context')
    @patch('app.core.workflow_engine.build_graph')
    def test_create_initial_state(self, mock_build_graph, mock_create_ctx):
        """Test creation of initial workflow state."""
        from app.core.workflow_engine import WorkflowEngine

        mock_create_ctx.return_value = Mock()
        mock_build_graph.return_value = Mock()

        engine = WorkflowEngine(enable_checkpointing=False)

        state = engine.create_initial_state(
            session_id="sess_001",
            patient_id="pat_001",
            doctor_id="doc_001"
        )

        assert state["session_id"] == "sess_001"
        assert state["patient_id"] == "pat_001"
        assert state["doctor_id"] == "doc_001"
        assert "conversation_log" in state
        assert "controls" in state
        assert isinstance(state["controls"]["trace_log"], list)

    @patch('app.core.workflow_engine.create_default_context')
    @patch('app.core.workflow_engine.build_graph')
    def test_get_config(self, mock_build_graph, mock_create_ctx):
        """Test _get_config helper method."""
        from app.core.workflow_engine import WorkflowEngine

        mock_create_ctx.return_value = Mock()
        mock_build_graph.return_value = Mock()

        engine = WorkflowEngine(enable_checkpointing=False)
        thread_id = "test_thread_123"

        config = engine._get_config(thread_id)

        assert config["configurable"]["thread_id"] == thread_id


@pytest.mark.unit
class TestGetWorkflowStatus:
    """Tests for workflow status retrieval."""

    @patch('app.core.workflow_engine.create_default_context')
    @patch('app.core.workflow_engine.build_graph')
    def test_get_workflow_status_not_found(self, mock_build_graph, mock_create_ctx):
        """Test getting status for nonexistent workflow."""
        from app.core.workflow_engine import WorkflowEngine

        mock_create_ctx.return_value = Mock()
        mock_graph = Mock()
        mock_graph.get_state = Mock(return_value=Mock(values=None))
        mock_build_graph.return_value = mock_graph

        engine = WorkflowEngine()

        status = engine.get_workflow_status("nonexistent_thread")

        assert status["status"] == "not_found"
        assert "message" in status

