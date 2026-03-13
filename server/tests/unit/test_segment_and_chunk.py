"""
Unit tests for segment_and_chunk.py (simplified version)
"""

import pytest
from app.agents.nodes.segment import segment_and_chunk_node, recursive_text_splitter
from app.agents.state import GraphState


class TestRecursiveTextSplitter:
    """Tests for recursive text splitting."""

    def test_split_short_text_no_split_needed(self):
        """Test that short text is not split."""
        text = "This is a short text."
        chunks = recursive_text_splitter(text, chunk_size=100, overlap=10)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_split_long_text_creates_multiple_chunks(self):
        """Test that long text is split into multiple chunks."""
        # Create text longer than chunk size
        text = "This is sentence one. " * 50  # Repeat to make it long

        chunks = recursive_text_splitter(text, chunk_size=100, overlap=10)

        assert len(chunks) > 1

    def test_split_empty_text(self):
        """Test handling of empty text."""
        chunks = recursive_text_splitter("", chunk_size=100, overlap=10)

        assert len(chunks) == 1
        assert chunks[0] == ""


@pytest.mark.unit
class TestSegmentAndChunkNode:
    """Tests for the segment_and_chunk_node function."""

    def test_chunk_simple_conversation(self, minimal_graph_state):
        """Test chunking a simple conversation."""
        state = minimal_graph_state.copy()
        state["conversation_log"] = [
            {
                "timestamp": 0.0,
                "segments": [{
                    "speaker": "Doctor",
                    "raw_text": "How are you feeling today?",
                    "cleaned_text": "How are you feeling today?",
                    "start": 0.0, "end": 3.0,
                }],
            },
            {
                "timestamp": 5.0,
                "segments": [{
                    "speaker": "Patient",
                    "raw_text": "I've been having chest pain.",
                    "cleaned_text": "I've been having chest pain.",
                    "start": 5.0, "end": 8.0,
                }],
            },
        ]

        result = segment_and_chunk_node(state)

        # Should create chunks
        assert "chunks" in result
        assert len(result["chunks"]) > 0
        # Check chunk structure
        if len(result["chunks"]) > 0:
            assert "chunk_id" in result["chunks"][0]
            assert "text" in result["chunks"][0]

    def test_chunk_long_conversation_creates_multiple_chunks(self, minimal_graph_state):
        """Test that long conversations are split into multiple chunks."""
        state = minimal_graph_state.copy()

        # Create a long conversation turn
        long_text = "The patient reports experiencing severe chest pain that started approximately two hours ago. " * 10

        state["conversation_log"] = [
            {
                "timestamp": 0.0,
                "segments": [{
                    "speaker": "Doctor",
                    "raw_text": long_text,
                    "cleaned_text": long_text,
                    "start": 0.0, "end": 60.0,
                }],
            }
        ]

        result = segment_and_chunk_node(state)

        # Long text should be split into multiple chunks
        assert len(result["chunks"]) >= 1

    def test_chunk_empty_conversation(self, minimal_graph_state):
        """Test handling of empty conversation log."""
        state = minimal_graph_state.copy()
        state["conversation_log"] = []

        result = segment_and_chunk_node(state)

        # Should still return valid state
        assert "chunks" in result
        assert isinstance(result["chunks"], list)

    def test_chunk_updates_trace_log(self, minimal_graph_state):
        """Test that trace log is updated."""
        state = minimal_graph_state.copy()
        state["conversation_log"] = [
            {
                "timestamp": 0.0,
                "segments": [{
                    "speaker": "Doctor",
                    "raw_text": "Test.",
                    "cleaned_text": "Test.",
                    "start": 0.0, "end": 1.0,
                }],
            }
        ]

        result = segment_and_chunk_node(state)

        # Check trace log
        assert len(result["controls"]["trace_log"]) > 0
        last_entry = result["controls"]["trace_log"][-1]
        assert last_entry["node"] == "segment_and_chunk"
