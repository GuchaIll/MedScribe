"""
Test suite for agent tools.

Tests:
- LLMTool budget management
- Tool error handling
- State synchronization
"""

import pytest
from unittest.mock import Mock, MagicMock
from app.agents.tools.llm import LLMTool


class TestLLMTool:
    """Tests for LLMTool."""

    def test_llm_tool_initialization(self):
        """Test LLMTool initialization."""
        tool = LLMTool(max_calls=20)
        assert tool.max_calls == 20
        assert tool.calls_used == 0
        assert tool.budget_remaining == 20
        assert not tool.budget_exhausted

    def test_llm_tool_with_factory(self):
        """Test LLMTool with factory function."""
        mock_client = Mock()
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=30)

        assert tool.client is mock_client
        factory.assert_called_once()

    def test_budget_tracking(self):
        """Test budget tracking across calls."""
        mock_client = Mock()
        mock_client.generate_response = Mock(return_value="Response")
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=5)

        for i in range(5):
            response = tool.generate("Prompt")
            assert response == "Response"
            assert tool.calls_used == i + 1
            assert tool.budget_remaining == 5 - (i + 1)

    def test_budget_exhaustion(self):
        """Test that budget exhaustion raises error."""
        mock_client = Mock()
        mock_client.generate_response = Mock(return_value="Response")
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=2)

        tool.generate("Prompt 1")
        tool.generate("Prompt 2")

        with pytest.raises(RuntimeError, match="LLM budget exhausted"):
            tool.generate("Prompt 3")

    def test_try_generate_fallback(self):
        """Test try_generate with fallback."""
        mock_client = Mock()
        mock_client.generate_response = Mock(return_value="Response")
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=1)

        result = tool.try_generate("Prompt 1")
        assert result == "Response"

        # Next call should use fallback
        result = tool.try_generate("Prompt 2", fallback="FALLBACK")
        assert result == "FALLBACK"

    def test_try_generate_exception_fallback(self):
        """Test try_generate returns fallback on exception."""
        mock_client = Mock()
        mock_client.generate_response = Mock(side_effect=Exception("API Error"))
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=100)

        result = tool.try_generate("Prompt", fallback="ERROR FALLBACK")
        assert result == "ERROR FALLBACK"

    def test_empty_prompt_validation(self):
        """Test that empty prompts are rejected."""
        mock_client = Mock()
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=10)

        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            tool.generate("")

        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            tool.generate("   ")

    def test_sync_budget_to_state(self):
        """Test syncing budget to workflow state."""
        mock_client = Mock()
        mock_client.generate_response = Mock(return_value="Response")
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=50)

        tool.generate("Prompt 1")
        tool.generate("Prompt 2")

        state = {}
        tool.sync_budget_to_state(state)

        assert state["controls"]["budget"]["llm_calls_used"] == 2
        assert state["controls"]["budget"]["max_total_llm_calls"] == 50

    def test_sync_preserves_existing_state(self):
        """Test that sync preserves existing state values."""
        mock_client = Mock()
        mock_client.generate_response = Mock(return_value="Response")
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=30)

        state = {
            "controls": {
                "other_field": "preserved",
                "budget": {"existing_key": "value"},
            }
        }

        tool.generate("Prompt")
        tool.sync_budget_to_state(state)

        assert state["controls"]["other_field"] == "preserved"
        assert state["controls"]["budget"]["existing_key"] == "value"
        assert state["controls"]["budget"]["llm_calls_used"] == 1


class TestLLMToolIntegration:
    """Integration tests for LLMTool."""

    def test_workflow_with_budget_control(self):
        """Test realistic workflow with budget constraints."""
        mock_client = Mock()
        responses = [f"Response {i}" for i in range(10)]
        mock_client.generate_response = Mock(side_effect=responses)
        factory = Mock(return_value=mock_client)
        tool = LLMTool(factory=factory, max_calls=5)

        # Simulate workflow that respects budget
        workflow_results = []
        for i in range(10):
            result = tool.try_generate(f"Prompt {i}", fallback=f"Fallback {i}")
            workflow_results.append(result)

        # First 5 should be real responses, rest should be fallbacks
        assert workflow_results[:5] == [f"Response {i}" for i in range(5)]
        assert workflow_results[5:] == [f"Fallback {i}" for i in range(5, 10)]
