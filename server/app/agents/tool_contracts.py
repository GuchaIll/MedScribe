"""
Shared tool registry contract — frozen v1 (agent refactor Phase 0).

One capability, three callers: Lane B compile stages, fixed assist chains, and
bounded assist agents call the same tool ids through one registry, so ranking,
citation rules, and receipts cannot drift. Patient / tenant scope is injected
by the runtime from the session, never supplied by a model. Types and
validators only; the registry lands in Phase 1 under server/app/agents/tools/.

Semantics and change control: docs/copilot_runtime_contract.md §6 and §10.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, get_args

RUNTIME_CONTRACT_VERSION = "1.1"

# A retrieval that finds nothing grounded returns ok=False with this error,
# so the answer layer says "no documented value" instead of guessing.
NO_SOURCE_ERROR = "no_source"

# Keys a model may never put in tool args. The runtime binds them from the session.
SCOPE_ARG_KEYS: FrozenSet[str] = frozenset({"patient_id", "tenant_id", "session_id", "doctor_id"})


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

ToolId = Literal[
    "retrieve_session",
    "retrieve_labs",
    "retrieve_docs",
    "retrieve_visits",
    "retrieve_for_candidates",
    "ingest_delta",
    "compare_findings",
    "generate_note",
    "safety_check",
]

ToolCategory = Literal["retrieval", "ingest", "compare", "note", "safety"]

# Target Lane B backbone (plan §4.2). graph.py keeps its current node names
# until Phase 3; these are the names tools declare as callers.
LaneBStage = Literal[
    "ingest_delta",
    "compile_candidates",
    "enrich",
    "materialize_record",
    "safety_and_validate",
    "finalize",
]

ToolCaller = Literal["lane_b_stage", "fixed_executor", "bounded_agent"]

# Where a tool may write. There is deliberately no PostgreSQL option:
# durable patient-record writes belong to Lane C only.
ToolWrites = Literal["none", "session_scratch", "session_draft"]

SourceKind = Literal[
    "session_transcript",
    "session_draft",
    "patient_snapshot",
    "uploaded_doc",
    "prior_labs",
    "prior_docs",
    "prior_visits",
]

TOOL_IDS: Tuple[str, ...] = get_args(ToolId)
TOOL_CATEGORIES: Tuple[str, ...] = get_args(ToolCategory)
LANE_B_STAGES: Tuple[str, ...] = get_args(LaneBStage)
TOOL_CALLERS: Tuple[str, ...] = get_args(ToolCaller)
TOOL_WRITES: Tuple[str, ...] = get_args(ToolWrites)
SOURCE_KINDS: Tuple[str, ...] = get_args(SourceKind)


# ---------------------------------------------------------------------------
# Registry specs
# ---------------------------------------------------------------------------

class ToolSpec(TypedDict):
    category: ToolCategory
    assist_callable: bool                   # fixed assist chains / jobs may call it
    agent_allowlisted: bool                 # bounded trajectory/compare agents may call it
    lane_b_stages: Tuple[LaneBStage, ...]   # compile stages allowed to call it; () = not a compile step
    writes: ToolWrites
    requires_citations: bool                # an ok result must carry at least one citation


TOOL_SPECS: Dict[str, ToolSpec] = {
    "retrieve_session": ToolSpec(
        category="retrieval", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_labs": ToolSpec(
        category="retrieval", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_docs": ToolSpec(
        category="retrieval", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_visits": ToolSpec(
        category="retrieval", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_for_candidates": ToolSpec(
        category="retrieval", assist_callable=False, agent_allowlisted=False,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "ingest_delta": ToolSpec(
        category="ingest", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("ingest_delta",), writes="session_scratch", requires_citations=False,
    ),
    "compare_findings": ToolSpec(
        category="compare", assist_callable=True, agent_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "generate_note": ToolSpec(
        category="note", assist_callable=True, agent_allowlisted=False,
        lane_b_stages=(), writes="session_draft", requires_citations=False,
    ),
    "safety_check": ToolSpec(
        category="safety", assist_callable=True, agent_allowlisted=False,
        lane_b_stages=("safety_and_validate",), writes="none", requires_citations=False,
    ),
}

AGENT_ALLOWLIST: FrozenSet[str] = frozenset(
    tool_id for tool_id, spec in TOOL_SPECS.items() if spec["agent_allowlisted"]
)


# ---------------------------------------------------------------------------
# Results and receipts
# ---------------------------------------------------------------------------

class Citation(TypedDict):
    source_kind: SourceKind
    source_id: str                  # doc id, lab row key, visit id, transcript segment id
    snippet: Optional[str]
    observed_at: Optional[str]      # ISO date of the underlying fact (lab draw, visit)
    score: Optional[float]


class ToolInvocationReceipt(TypedDict):
    """Payload of the internal ``tool.invocation`` event; also appended to controls.trace_log."""
    contract_version: str
    invocation_id: str
    session_id: str                 # injected by runtime, never model-supplied
    tool_id: ToolId
    tool_version: str
    caller: ToolCaller
    caller_ref: str                 # Lane B stage name, or intent.decision event_id
    args_hash: str                  # hash only — no PHI or secrets in receipts
    ok: bool
    error: Optional[str]
    cache_hit: bool                 # reused session artifacts instead of re-ingesting
    latency_ms: float
    source_refs: List[str]
    created_at: str                 # ISO-8601


class ToolResult(TypedDict):
    tool_id: ToolId
    ok: bool
    data: Dict[str, Any]
    citations: List[Citation]
    error: Optional[str]
    receipt: ToolInvocationReceipt


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def find_scope_keys(args: Any, path: str = "") -> List[str]:
    """Return dotted paths of scope keys anywhere inside model-supplied args."""
    found: List[str] = []
    if isinstance(args, dict):
        for key, value in args.items():
            here = f"{path}.{key}" if path else str(key)
            if key in SCOPE_ARG_KEYS:
                found.append(here)
            found.extend(find_scope_keys(value, here))
    elif isinstance(args, list):
        for index, value in enumerate(args):
            found.extend(find_scope_keys(value, f"{path}[{index}]"))
    return found


def validate_model_tool_args(tool_id: str, args: Any) -> List[str]:
    """Return violations for tool args proposed by a model (empty list = valid)."""
    errors: List[str] = []
    if tool_id not in TOOL_SPECS:
        errors.append(f"unknown tool {tool_id!r}")
    if not isinstance(args, dict):
        errors.append("args must be an object")
        return errors
    scope_paths = find_scope_keys(args)
    if scope_paths:
        errors.append(f"scope keys are injected by the runtime, not model args: {scope_paths}")
    return errors


def validate_tool_result(result: Dict[str, Any]) -> List[str]:
    """Return violations for a ToolResult (empty list = valid).

    Enforces the citation-presence floor: tools that must cite cannot return
    ok=True without citations. Citation *correctness* is the grounding
    validator's job (executor_contract.GroundingReport).
    """
    missing = set(ToolResult.__annotations__) - set(result)
    if missing:
        return [f"missing fields: {sorted(missing)}"]

    spec = TOOL_SPECS.get(result["tool_id"])
    if spec is None:
        return [f"unknown tool {result['tool_id']!r}"]

    errors: List[str] = []
    if not isinstance(result["ok"], bool):
        errors.append("ok must be bool")

    citations = result["citations"]
    if not isinstance(citations, list):
        errors.append("citations must be a list")
        citations = []
    for citation in citations:
        if (
            not isinstance(citation, dict)
            or citation.get("source_kind") not in SOURCE_KINDS
            or not citation.get("source_id")
        ):
            errors.append("each citation needs a known source_kind and a source_id")
            break

    if result["ok"] is True and spec["requires_citations"] and not citations:
        errors.append(f"{result['tool_id']} returned ok without citations (ungrounded)")
    if result["ok"] is False and not isinstance(result["error"], str):
        errors.append("failed result must carry an error string")

    return errors
