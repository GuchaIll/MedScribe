"""
Agent nodes — one file per pipeline step.

Each node is a pure function: ``(state[, ctx]) -> state``.
Nodes that need external services accept an ``AgentContext`` as second arg.
"""

from .ingest import ingest_transcript_node
from .clean import clean_transcription_node
from .normalize import normalize_transcript_node
from .segment import segment_and_chunk_node
from .extract import extract_candidates_node
from .evidence import retrieve_evidence_node
from .fill_record import fill_structured_record_node
from .clinical_suggestions import clinical_suggestions_node
from .validate import validate_and_score_node
from .repair import repair_node
from .conflicts import conflict_resolution_node
from .review_gate import human_review_gate_node
from .generate_note import generate_note_node
from .package import package_outputs_node

__all__ = [
    "ingest_transcript_node",
    "clean_transcription_node",
    "normalize_transcript_node",
    "segment_and_chunk_node",
    "extract_candidates_node",
    "retrieve_evidence_node",
    "fill_structured_record_node",
    "clinical_suggestions_node",
    "validate_and_score_node",
    "repair_node",
    "conflict_resolution_node",
    "human_review_gate_node",
    "generate_note_node",
    "package_outputs_node",
]
