"""
Executor contract — frozen v1 (agent refactor Phase 0).

The gate outputs addressee + task slots; the executor owns the plan.

- Fixed chains where the plan is known up front, the output persists, or the
  result must be reproducible (factoid, safety, jobs).
- Bounded agents only where the next step depends on the last result
  (trajectory, compare): allowlisted tools, a call cap, a wall-clock budget,
  runtime-injected scope, and a grounding check before anything renders.

Semantics: docs/copilot_runtime_contract.md §2 and §5.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Sequence, Tuple, TypedDict, get_args

from app.agents.tool_contracts import TOOL_SPECS, validate_model_tool_args

ExecutorMode = Literal["fixed", "bounded_agent"]
EXECUTOR_MODES: Tuple[str, ...] = get_args(ExecutorMode)

TASK_EXECUTOR_MODE: Dict[str, str] = {
    "factoid": "fixed",
    "safety": "fixed",
    "note": "fixed",
    "compile": "fixed",
    "doc_ingest": "fixed",
    "session_control": "fixed",
    "unknown": "fixed",
    "trajectory": "bounded_agent",
    "compare": "bounded_agent",
}

# Tool order for non-agent tasks. "factoid" is a fallback chain: stop at the
# first grounded hit. Empty chains hand off instead of calling tools:
# compile enqueues Lane B, session_control confirms then Lane C, unknown clarifies.
FIXED_TOOL_CHAINS: Dict[str, Tuple[str, ...]] = {
    "factoid": ("retrieve_session", "retrieve_labs", "retrieve_docs"),
    "safety": ("retrieve_session", "safety_check"),
    "note": ("generate_note",),
    "doc_ingest": ("ingest_delta",),
    "compile": (),
    "session_control": (),
    "unknown": (),
}

# Provisional (plan §3.0: 4–6 calls plus a wall-clock budget); tuned in Phase 2.
MAX_AGENT_TOOL_CALLS = 6
AGENT_WALL_CLOCK_BUDGET_MS = 8000

GroundingVerdict = Literal["render", "refuse"]


class AgentStep(TypedDict):
    tool_id: str
    args: Dict[str, Any]            # hints only; scope keys are rejected


class GroundingReport(TypedDict):
    """Post-hoc check before an assist answer renders.

    Groundedness means citation correctness, not citation presence: each
    patient-fact claim's citation must resolve to a real source that contains
    the stated value.
    """
    claims_checked: int
    unsupported_claim_ids: List[str]
    verdict: GroundingVerdict


def validate_agent_step(step: Dict[str, Any], *, calls_made: int, elapsed_ms: float) -> List[str]:
    """Return reasons the runtime must refuse a bounded-agent step (empty list = run it)."""
    tool_id = step.get("tool_id", "")
    errors = validate_model_tool_args(tool_id, step.get("args", {}))

    spec = TOOL_SPECS.get(tool_id)
    if spec is not None and not spec["agent_allowlisted"]:
        errors.append(f"tool {tool_id!r} is not on the bounded-agent allowlist")
    if calls_made >= MAX_AGENT_TOOL_CALLS:
        errors.append(f"call cap reached ({MAX_AGENT_TOOL_CALLS})")
    if elapsed_ms >= AGENT_WALL_CLOCK_BUDGET_MS:
        errors.append(f"wall-clock budget exhausted ({AGENT_WALL_CLOCK_BUDGET_MS} ms)")
    return errors


def grounding_verdict(unsupported_claim_ids: Sequence[str]) -> GroundingVerdict:
    """Any unsupported claim blocks rendering; the executor refuses or re-drafts."""
    return "refuse" if unsupported_claim_ids else "render"
