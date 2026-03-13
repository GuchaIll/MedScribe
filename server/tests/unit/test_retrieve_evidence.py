"""
Unit tests for retrieve_evidence.py (simplified version)
"""

import pytest
from app.agents.nodes.evidence import (
    retrieve_evidence_node,
    fuzzy_similarity,
    normalize_text_for_matching
)
from app.agents.state import GraphState
from tests.helpers import make_test_context


class TestNormalizeTextForMatching:
    """Tests for text normalization."""

    def test_normalize_lowercase(self):
        """Test that text is converted to lowercase."""
        result = normalize_text_for_matching("HELLO WORLD")
        assert result == "hello world"

    def test_normalize_removes_extra_whitespace(self):
        """Test that extra whitespace is removed."""
        result = normalize_text_for_matching("hello    world")
        assert result == "hello world"

    def test_normalize_empty_string(self):
        """Test handling of empty string."""
        result = normalize_text_for_matching("")
        assert result == ""


class TestFuzzySimilarity:
    """Tests for fuzzy similarity calculation."""

    def test_similarity_identical_strings(self):
        """Test that identical strings have 1.0 similarity."""
        similarity = fuzzy_similarity("chest pain", "chest pain")
        assert similarity == 1.0

    def test_similarity_different_strings(self):
        """Test that different strings have low similarity."""
        similarity = fuzzy_similarity("chest pain", "headache")
        assert similarity < 0.5

    def test_similarity_similar_strings(self):
        """Test that similar strings have high similarity."""
        similarity = fuzzy_similarity(
            "patient has chest pain",
            "patient presents with chest pain"
        )
        assert similarity > 0.6


@pytest.mark.unit
class TestRetrieveEvidenceNode:
    """Tests for the retrieve_evidence_node function."""

    def test_retrieve_evidence_basic(self, minimal_graph_state, sample_candidate_facts, sample_chunks):
        """Test basic evidence retrieval."""
        state = minimal_graph_state.copy()
        state["candidate_facts"] = sample_candidate_facts[:1]  # Just one fact
        state["chunks"] = sample_chunks

        result = retrieve_evidence_node(state, make_test_context())

        # Should create evidence map
        assert "evidence_map" in result
        assert len(result["evidence_map"]) > 0

    def test_retrieve_evidence_multiple_facts(self, minimal_graph_state, sample_candidate_facts, sample_chunks):
        """Test evidence retrieval for multiple facts."""
        state = minimal_graph_state.copy()
        state["candidate_facts"] = sample_candidate_facts
        state["chunks"] = sample_chunks

        result = retrieve_evidence_node(state, make_test_context())

        # Should have evidence for facts
        assert len(result["evidence_map"]) == len(sample_candidate_facts)

    def test_retrieve_evidence_no_chunks(self, minimal_graph_state, sample_candidate_facts):
        """Test evidence retrieval with no chunks available."""
        state = minimal_graph_state.copy()
        state["candidate_facts"] = sample_candidate_facts
        state["chunks"] = []

        result = retrieve_evidence_node(state, make_test_context())

        # Should still create evidence map
        assert "evidence_map" in result

    def test_retrieve_evidence_no_facts(self, minimal_graph_state, sample_chunks):
        """Test evidence retrieval with no candidate facts."""
        state = minimal_graph_state.copy()
        state["candidate_facts"] = []
        state["chunks"] = sample_chunks

        result = retrieve_evidence_node(state, make_test_context())

        # Evidence map should be empty
        assert len(result["evidence_map"]) == 0

    def test_retrieve_evidence_updates_trace_log(self, minimal_graph_state, sample_candidate_facts, sample_chunks):
        """Test that trace log is updated."""
        state = minimal_graph_state.copy()
        state["candidate_facts"] = sample_candidate_facts
        state["chunks"] = sample_chunks

        result = retrieve_evidence_node(state, make_test_context())

        # Check trace log
        assert len(result["controls"]["trace_log"]) > 0
        last_entry = result["controls"]["trace_log"][-1]
        assert last_entry["node"] == "retrieve_evidence"
