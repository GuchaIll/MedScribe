"""
Executor contract — v1.2 (agent refactor Phase 1A, #50).

The gate outputs addressee + task slots (with sub_asks); dispatch_assist()
picks the execution path from those slots via a pure code table (§12.4).

- Fixed workflows where the evidence class is known and independent.
- Fan-out when multiple independent workflows fit within MAX_FANOUT_WORKFLOWS.
- planning_agent when sub-asks have dependencies, no_workflow class accepted,
  or a fixed workflow hands off via needs_plan (§12.5).
- clarify when scope is underspecified or sub-asks conflict.

Provisional numbers are imported from agents/config.py so they live in one
config file and are not duplicated in contract types.

Semantics: docs/copilot_runtime_contract.md §2, §5, §12.4–12.5.

Changes from 1.1:
- ExecutorMode: bounded_agent -> planning_agent (§12.5).
- DispatchValue added: silent | clarify | workflow | fanout | planning_agent.
- dispatch_assist() pure function added (§12.4 table).
- WorkflowName mapping added.
- WorkerPlan / PlanTask added; needs_scope replaces clarify_question (§12.5).
- ClarifyKind / ScopeChoice / ClarifyRequest added (§12.4).
- WorkflowState added for needs_plan handoff (§12.5).
- Provisional constants imported from config.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, TypedDict, get_args

from app.agents.config import (
    MAX_FANOUT_WORKFLOWS,
    QUERY_MATERIALIZATION_WAIT_MS,
    SUB_ASK_MIN_CONFIDENCE,
)
from app.agents.tool_contracts import TOOL_SPECS, validate_model_tool_args

# Re-export so callers that previously imported from here still work.
__all__ = [
    "SUB_ASK_MIN_CONFIDENCE",
    "MAX_FANOUT_WORKFLOWS",
    "QUERY_MATERIALIZATION_WAIT_MS",
]

# ---------------------------------------------------------------------------
# Executor modes
# ---------------------------------------------------------------------------

# bounded_agent is retired in 1.2; planning_agent is reached by dispatch or handoff.
ExecutorMode = Literal["fixed", "planning_agent"]
EXECUTOR_MODES: Tuple[str, ...] = get_args(ExecutorMode)

# In 1.2 every task has a fixed workflow path; planning_agent is reached only
# through dispatch_assist() or a needs_plan handoff, not by task label alone.
TASK_EXECUTOR_MODE: Dict[str, str] = {
    "factoid": "fixed",
    "safety": "fixed",
    "note": "fixed",
    "compile": "fixed",
    "doc_ingest": "fixed",
    "session_control": "fixed",
    "unknown": "fixed",
    "trajectory": "fixed",  # fixed workflow in 1.2 (was bounded_agent in 1.1)
    "compare": "fixed",     # fixed workflow in 1.2 (was bounded_agent in 1.1)
}

# Tool order for non-agent fixed tasks. "factoid" is a fallback chain: stop at
# the first grounded hit. Empty chains hand off instead of calling tools.
FIXED_TOOL_CHAINS: Dict[str, Tuple[str, ...]] = {
    "factoid": ("retrieve_session", "retrieve_structured", "retrieve_docs"),
    "safety": ("retrieve_session", "check_med_conflicts", "check_dosage", "check_metric_alerts"),
    "note": ("generate_note",),
    "doc_ingest": ("ingest_delta",),
    "compile": (),
    "session_control": (),
    "unknown": (),
    "trajectory": ("get_patient_profile", "retrieve_structured", "retrieve_source_chunks"),
    "compare": ("get_patient_profile", "retrieve_structured", "retrieve_source_chunks", "compare_findings"),
}

# Provisional planner budget (carried from §5.2 / 1.1 contract).
MAX_AGENT_TOOL_CALLS = 6
AGENT_WALL_CLOCK_BUDGET_MS = 8000

# ---------------------------------------------------------------------------
# Dispatch types (§12.4)
# ---------------------------------------------------------------------------

DispatchValue = Literal["silent", "clarify", "workflow", "fanout", "planning_agent"]
DISPATCH_VALUES: Tuple[str, ...] = get_args(DispatchValue)

# Maps a task subtype to the workflow name used in the assist graph.
WORKFLOW_NAME: Dict[str, str] = {
    "factoid": "general_cascade",
    "trajectory": "trajectory",
    "compare": "compare",
    "safety": "safety",
    "session": "session",
    "measurement": "measurement",
    "document": "document",
}

GroundingVerdict = Literal["render", "refuse"]


# ---------------------------------------------------------------------------
# Clarify types (§12.4)
# ---------------------------------------------------------------------------

ClarifyKind = Literal["scope", "reading", "rephrase", "narrow"]
CLARIFY_KINDS: Tuple[str, ...] = get_args(ClarifyKind)


class ScopeChoice(TypedDict):
    """A single candidate scope offered to the physician (§12.4).

    Candidates come from the scope library only; the model cannot invent them.
    Personalized wording requires supporting_fact_ids from patient context.
    """
    scope_id: str
    rank: int
    label: str
    supporting_fact_ids: List[str]   # empty = generic (not personalized)
    expands_to: List[str]            # sub_ask_ids this choice resolves to


class ClarifyRequest(TypedDict):
    """Structured clarification request — no model-written free-text question (§12.4, §12.8 invariant 2)."""
    kind: ClarifyKind
    choices: List[ScopeChoice]
    allow_free_text: bool


# ---------------------------------------------------------------------------
# Planner types (§12.5)
# ---------------------------------------------------------------------------

class PlanTask(TypedDict):
    """A single step in a WorkerPlan, addressing one sub-ask."""
    task_id: str
    tool_id: str
    args: Dict[str, Any]            # hints only; scope keys are rejected by the registry
    depends_on: List[str]           # task_ids this step waits for
    sub_ask_id: str                 # which SubAsk this covers


class WorkerPlan(TypedDict):
    """Validated plan returned by the planning agent before any tool runs (§12.5).

    The planner validates: refs exist in PLANNER_ALLOWLIST, no scope keys,
    tasks are acyclic, every sub-ask is covered, total expanded tool calls <= 6.
    needs_scope is set when the plan cannot proceed without a physician scope
    choice (replaces the old clarify_question field from 1.1).
    """
    plan_id: str
    tasks: List[PlanTask]
    synthesis_goal: str
    needs_scope: Optional[str]      # human-readable reason; non-null blocks execution


# ---------------------------------------------------------------------------
# Handoff type (§12.5)
# ---------------------------------------------------------------------------

class WorkflowState(TypedDict):
    """State passed from a fixed workflow to the planner on a needs_plan handoff (§12.5).

    Goal and scope are fixed by the fixed workflow; the planner may not change
    them. The planner plans only for remaining_requirements and must not re-run
    any entry in sources_checked.
    """
    workflow_id: str
    reason: str                             # why the fixed workflow ran out
    goal: str                               # immutable
    scope: Dict[str, Any]                   # immutable
    required_evidence: List[str]
    remaining_requirements: List[str]
    acquired: List[Dict[str, Any]]          # evidence items with citations
    sources_checked: List[Dict[str, str]]   # [{"tool_id": ..., "args_hash": ...}]
    as_of_receipt: str                      # ISO-8601 cutoff shared with the request
    latency_remaining_ms: float


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

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
    """Return reasons the runtime must refuse a planning-agent step (empty list = run it)."""
    tool_id = step.get("tool_id", "")
    errors = validate_model_tool_args(tool_id, step.get("args", {}))

    spec = TOOL_SPECS.get(tool_id)
    if spec is not None and not spec["planner_allowlisted"]:
        errors.append(f"tool {tool_id!r} is not on the planner allowlist")
    if calls_made >= MAX_AGENT_TOOL_CALLS:
        errors.append(f"call cap reached ({MAX_AGENT_TOOL_CALLS})")
    if elapsed_ms >= AGENT_WALL_CLOCK_BUDGET_MS:
        errors.append(f"wall-clock budget exhausted ({AGENT_WALL_CLOCK_BUDGET_MS} ms)")
    return errors


def grounding_verdict(unsupported_claim_ids: Sequence[str]) -> GroundingVerdict:
    """Any unsupported claim blocks rendering; the executor refuses or re-drafts."""
    return "refuse" if unsupported_claim_ids else "render"


# ---------------------------------------------------------------------------
# Dispatch (§12.4 table)
# ---------------------------------------------------------------------------

def _is_underspecified(sub_ask: Dict[str, Any]) -> bool:
    """A sub-ask is underspecified when it has no entity or domain hints.

    A time range alone does not scope a retrieval; the downstream workflow
    cannot determine what to look for without at least one hint.
    """
    return not sub_ask.get("entity_hints") and not sub_ask.get("domain_hints")


def _accepted_classes(sub_ask: Dict[str, Any]) -> List[str]:
    """Return evidence classes whose calibrated score meets SUB_ASK_MIN_CONFIDENCE."""
    return [
        cls for cls, score in sub_ask.get("class_scores", {}).items()
        if isinstance(score, (int, float)) and score >= SUB_ASK_MIN_CONFIDENCE
    ]


def dispatch_assist(channel: str, slots: Dict[str, Any]) -> DispatchValue:
    """Pure dispatch function — first matching rule wins (§12.4 table).

    Args:
        channel: one of CHANNELS from schemas.py.
        slots:   a TaskSlots dict (or compatible mapping) from the gate.

    Returns:
        A DispatchValue indicating how the executor should proceed.
    """
    # Rule 1: ambient transcript is always silent in v1.
    if channel == "ambient_transcript":
        return "silent"

    sub_asks: List[Dict[str, Any]] = slots.get("sub_asks", [])
    readings_conflict: bool = bool(slots.get("readings_conflict", False))

    # Classify each sub-ask.
    accepted_by_ask = [_accepted_classes(sa) for sa in sub_asks]
    any_no_accepted = not sub_asks or any(len(a) == 0 for a in accepted_by_ask)
    any_underspecified = any(_is_underspecified(sa) for sa in sub_asks)
    any_no_workflow = any("no_workflow" in classes for classes in accepted_by_ask)
    any_depends_on = any(sa.get("depends_on") for sa in sub_asks)

    # Rule 2: unclear, conflicted, or underspecified -> clarify.
    if any_no_accepted or any_underspecified or readings_conflict:
        return "clarify"

    # Rule 3: dependencies or no_workflow class -> planning_agent.
    if any_depends_on or any_no_workflow:
        return "planning_agent"

    # Rules 4–6: count how many independent sub-asks have an accepted class.
    independent = [
        sa for sa, classes in zip(sub_asks, accepted_by_ask)
        if classes and not sa.get("depends_on") and "no_workflow" not in classes
    ]

    # Rule 4: exactly one independent sub-ask -> single workflow.
    if len(independent) == 1:
        return "workflow"

    # Rule 5: within fan-out cap -> parallel fixed workflows.
    if 1 < len(independent) <= MAX_FANOUT_WORKFLOWS:
        return "fanout"

    # Rule 6: over cap -> narrow clarify.
    return "clarify"
