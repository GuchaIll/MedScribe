"""
Preprocess Node -- Merged ingest + normalize + segment.

Collapses three serial pure-computation nodes into a single graph step
to eliminate inter-node overhead on the critical path. All logic is
unchanged; only the graph-level serialization is removed.
"""

from datetime import datetime
from typing import List

from ..state import GraphState
from .ingest import ingest_transcript_node
from .normalize import normalize_transcript_node
from .segment import segment_and_chunk_node


def preprocess_node(state: GraphState) -> GraphState:
    """
    Run ingest -> normalize -> segment as a single atomic graph node.

    Each sub-step is still the original function, so behaviour is identical
    to the three-node pipeline. The only difference is that LangGraph sees
    one node transition instead of three, saving ~2 checkpoint writes and
    the associated serialization overhead (~200-400 ms each).
    """
    state = ingest_transcript_node(state)
    state = normalize_transcript_node(state)
    state = segment_and_chunk_node(state)

    # Record consolidated trace entry
    controls = state.get("controls", {})
    controls.setdefault("trace_log", []).append({
        "node": "preprocess",
        "action": "completed",
        "sub_steps": ["ingest", "normalize", "segment"],
        "chunk_count": len(state.get("chunks", [])),
        "timestamp": datetime.now().isoformat(),
    })
    state["controls"] = controls

    return state
