"""
LangGraph Workflow — Clean Graph Definition.

Single source of truth for the clinical transcription pipeline topology.
Replaces the inline graph-building in langgraph_runner.py with a
context-aware, testable graph builder.

Nodes receive services through AgentContext (Anthropic agent pattern) 
rather than importing them directly.

Pipeline topology (with DB integration):
  greeting → load_patient_context → preprocess (ingest+normalize+segment) → clean →
  extract (parallel query-value) → diagnostic_reasoning → evidence →
  fill_record → clinical_suggestions → validate →
  [repair loop | conflict_resolution | human_review_gate] →
  generate_note → package_outputs → persist_results → END
"""

from langgraph.graph import StateGraph, END

from .state import GraphState
from .config import AgentContext, make_node, create_default_context

# Node imports — each is a pure function (state[, ctx]) -> state
from .nodes.load_patient_context import load_patient_context_node
from .nodes.preprocess import preprocess_node
from .nodes.clean import clean_transcription_node
from .nodes.extract import extract_candidates_node
from .nodes.diagnostic_reasoning import diagnostic_reasoning_node
from .nodes.evidence import retrieve_evidence_node
from .nodes.fill_record import fill_structured_record_node
from .nodes.clinical_suggestions import clinical_suggestions_node
from .nodes.validate import validate_and_score_node
from .nodes.repair import repair_node
from .nodes.conflicts import conflict_resolution_node
from .nodes.review_gate import human_review_gate_node
from .nodes.generate_note import generate_note_node
from .nodes.package import package_outputs_node
from .nodes.persist_results import persist_results_node


# ─── Greeting (lightweight, no context needed) ─────────────────────────────

def greeting_node(state: GraphState) -> GraphState:
    """Welcome message — seeds initial state."""
    state = {**state}
    state["message"] = (
        f"Welcome back Dr. {state.get('doctor_id', 'Unknown')}. "
        "I'm Judith, ready to assist with today's transcription session."
    )
    return state


# ─── Routing helpers ────────────────────────────────────────────────────────

def _route_after_validate(state: GraphState) -> str:
    """Decide next step after validation: repair, conflict resolution, review, or note."""
    report = state.get("validation_report") or {}
    controls = state.get("controls", {})
    repair_attempts = controls.get("attempts", {}).get("repair", 0)

    # Repair loop (max 3 iterations)
    if report.get("schema_errors") and repair_attempts < 3:
        return "repair"
    if report.get("conflicts"):
        return "conflict_resolution"
    if report.get("needs_review"):
        return "human_review_gate"
    return "generate_note"


def _route_after_conflict(state: GraphState) -> str:
    """Decide next step after conflict resolution."""
    report = state.get("conflict_report") or {}
    if report.get("unresolved"):
        return "human_review_gate"
    return "generate_note"


# ─── Graph builder ──────────────────────────────────────────────────────────

def build_graph(
    ctx: AgentContext | None = None,
    enable_interrupts: bool = True,
):
    """
    Build and compile the clinical transcription LangGraph.

    Args:
        ctx:               AgentContext with injected services.
                           Falls back to ``create_default_context()`` if None.
        enable_interrupts: Pause before human_review_gate for approval.

    Returns:
        Compiled LangGraph application.
    """
    if ctx is None:
        ctx = create_default_context()

    graph = StateGraph(GraphState)

    # ── Register nodes (context injected via make_node) ─────────────────────
    nodes = {
        "greeting":               greeting_node,
        "load_patient_context":   load_patient_context_node,
        "preprocess":             preprocess_node,
        "clean_transcription":    clean_transcription_node,
        "extract_candidates":     extract_candidates_node,
        "diagnostic_reasoning_node": diagnostic_reasoning_node,
        "retrieve_evidence":      retrieve_evidence_node,
        "fill_structured_record": fill_structured_record_node,
        "clinical_suggestions_node": clinical_suggestions_node,
        "validate_and_score":     validate_and_score_node,
        "repair":                 repair_node,
        "conflict_resolution":    conflict_resolution_node,
        "human_review_gate":      human_review_gate_node,
        "generate_note":          generate_note_node,
        "package_outputs":        package_outputs_node,
        "persist_results":        persist_results_node,
    }

    for name, fn in nodes.items():
        graph.add_node(name, make_node(fn, ctx))

    # ── Edges: linear pipeline with DB bookends ─────────────────────────────
    graph.set_entry_point("greeting")
    graph.add_edge("greeting", "load_patient_context")
    graph.add_edge("load_patient_context", "preprocess")
    graph.add_edge("preprocess", "clean_transcription")
    graph.add_edge("clean_transcription", "extract_candidates")
    graph.add_edge("extract_candidates", "diagnostic_reasoning_node")
    graph.add_edge("diagnostic_reasoning_node", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "fill_structured_record")
    graph.add_edge("fill_structured_record", "clinical_suggestions_node")
    graph.add_edge("clinical_suggestions_node", "validate_and_score")

    # ── Conditional edges: validate → repair loop / conflicts / review ──────
    graph.add_conditional_edges("validate_and_score", _route_after_validate)
    graph.add_conditional_edges("conflict_resolution", _route_after_conflict)

    graph.add_edge("repair", "validate_and_score")  # loop back
    graph.add_edge("human_review_gate", "package_outputs")
    graph.add_edge("generate_note", "package_outputs")
    graph.add_edge("package_outputs", "persist_results")
    graph.add_edge("persist_results", END)

    # ── Compile ─────────────────────────────────────────────────────────────
    # NOTE: Redis checkpointing is disabled until langgraph is upgraded to
    # 0.3+ (currently 0.1.19 which is incompatible with
    # langgraph-checkpoint 4.x put() signature).  The pipeline streams
    # state via graph.stream() and accumulates final_state locally, so
    # checkpointing is not required for correctness.
    compile_kwargs: dict = {}

    if enable_interrupts:
        compile_kwargs["interrupt_before"] = ["human_review_gate"]

    return graph.compile(**compile_kwargs)
