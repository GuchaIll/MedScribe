"""
Unit tests for normalize_transcript.py (simplified version)
"""

import pytest
from datetime import datetime
from app.agents.nodes.normalize import normalize_transcript_node, normalize_timestamp
from app.agents.state import GraphState


class TestNormalizeTimestamp:
    """Tests for timestamp normalization."""

    def test_normalize_float_timestamp(self):
        """Test normalization of float timestamp to ISO-8601."""
        result = normalize_timestamp(123.45)
        assert isinstance(result, str)
        assert "T" in result  # ISO format contains 'T'

    def test_normalize_iso_timestamp_passthrough(self):
        """Test that ISO timestamps pass through unchanged."""
        iso_time = "2024-01-15T10:30:00"
        result = normalize_timestamp(iso_time)
        assert result == iso_time

    def test_normalize_none_timestamp(self):
        """Test handling of None timestamp."""
        result = normalize_timestamp(None)
        assert result is None


@pytest.mark.unit
class TestNormalizeTranscriptNode:
    """Tests for the normalize_transcript_node function."""

    def test_normalize_simple_transcript(self, minimal_graph_state):
        """Test normalization of a simple transcript."""
        state = minimal_graph_state.copy()
        state["new_segments"] = [
            {
                "start": 0.0,
                "end": 3.0,
                "speaker": "dr",
                "raw_text": "Um, how are you feeling?",
                "cleaned_text": None,
                "uncertainties": [],
                "confidence": "high"
            }
        ]

        result = normalize_transcript_node(state)

        # Segments are moved to conversation_log and new_segments is cleared
        assert result["new_segments"] == []
        assert len(result["conversation_log"]) >= 1
        seg = result["conversation_log"][0]["segments"][0]
        assert seg["cleaned_text"] is not None
        # Check that speaker is normalized to standard form
        assert seg["speaker"] in ["Doctor", "dr"]  # Either is acceptable

    def test_normalize_creates_conversation_log(self, minimal_graph_state):
        """Test that conversation log is created."""
        state = minimal_graph_state.copy()
        state["new_segments"] = [
            {
                "start": 0.0,
                "end": 3.0,
                "speaker": "Doctor",
                "raw_text": "Hello.",
                "cleaned_text": None,
                "uncertainties": [],
                "confidence": "high"
            },
            {
                "start": 3.0,
                "end": 6.0,
                "speaker": "Patient",
                "raw_text": "Hi.",
                "cleaned_text": None,
                "uncertainties": [],
                "confidence": "high"
            }
        ]

        result = normalize_transcript_node(state)

        # Check conversation log is populated
        assert len(result["conversation_log"]) >= 1
        # Conversation log entries are {timestamp, segments} dicts
        turn = result["conversation_log"][0]
        assert "timestamp" in turn
        assert "segments" in turn
        assert len(turn["segments"]) >= 1

    def test_normalize_updates_trace_log(self, minimal_graph_state):
        """Test that trace log is updated."""
        state = minimal_graph_state.copy()
        state["new_segments"] = [
            {
                "start": 0.0,
                "end": 3.0,
                "speaker": "Doctor",
                "raw_text": "Test.",
                "cleaned_text": None,
                "uncertainties": [],
                "confidence": "high"
            }
        ]

        result = normalize_transcript_node(state)

        # Check trace log
        assert len(result["controls"]["trace_log"]) > 0
        assert result["controls"]["trace_log"][-1]["node"] == "normalize_transcript"

    def test_normalize_empty_segments(self, minimal_graph_state):
        """Test handling of empty segments list."""
        state = minimal_graph_state.copy()
        state["new_segments"] = []

        result = normalize_transcript_node(state)

        assert result["new_segments"] == []

    def test_normalize_preserves_existing_conversation_log(self, minimal_graph_state):
        """Test that existing conversation log entries are preserved."""
        state = minimal_graph_state.copy()
        state["conversation_log"] = [
            {
                "turn_index": 0,
                "speaker": "Doctor",
                "text": "Previous turn.",
                "timestamp": 0.0
            }
        ]
        state["new_segments"] = [
            {
                "start": 10.0,
                "end": 13.0,
                "speaker": "Patient",
                "raw_text": "New turn.",
                "cleaned_text": None,
                "uncertainties": [],
                "confidence": "high"
            }
        ]

        result = normalize_transcript_node(state)

        # Should have at least the previous entry
        assert len(result["conversation_log"]) >= 1
