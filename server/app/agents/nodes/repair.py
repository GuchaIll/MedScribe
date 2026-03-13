from ..state import GraphState


def repair_node(state: GraphState) -> GraphState:
    """Repair loop for schema violations or missing fields."""
    state = state.copy()
    controls = state.setdefault("controls", {"attempts": {}, "budget": {}, "trace_log": []})
    attempts = controls.setdefault("attempts", {})
    attempts["repair"] = attempts.get("repair", 0) + 1

    validation = state.get("validation_report") or {}
    if validation.get("schema_errors") or validation.get("missing_fields"):
        state.setdefault("flags", {})["needs_review"] = attempts["repair"] > 1

    return state
