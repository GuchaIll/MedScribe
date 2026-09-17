"""
Shared tool registry contract — v1.2 (agent refactor Phase 1A, #50).

One capability, three callers: Lane B compile stages, fixed assist workflows,
and the planning agent call the same tool ids through one registry, so ranking,
citation rules, and receipts cannot drift. Patient / tenant scope is injected
by the runtime from the session, never supplied by a model. Types and
validators only; the registry implementation lands in Phase 1 under
server/app/agents/tools/.

Semantics and change control: docs/copilot_runtime_contract.md §6 and §10.

Changes from 1.1:
- Tool ids v2: retrieve_labs -> retrieve_structured; safety_check split into
  check_med_conflicts / check_dosage / check_metric_alerts; get_patient_profile
  and retrieve_source_chunks added; compute tools added (§12.7).
- Citation gains received_at, evidence_state, locator (§12.2).
- Claim and Derivation types added for the strict grounding validator (§12.7).
- ToolCaller: bounded_agent -> planning_agent (§12.5).
- NOT_COVERED_ERROR added for safety tools that do not cover the requested check.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, Union, get_args

RUNTIME_CONTRACT_VERSION = "1.2"

# A retrieval that finds nothing grounded returns ok=False with this error,
# so the answer layer says "no documented value" instead of guessing.
NO_SOURCE_ERROR = "no_source"

# Safety tools return this error when the requested check is outside the
# current rule set's coverage (e.g. a drug not in the formulary table).
NOT_COVERED_ERROR = "not_covered"

# Keys a model may never put in tool args. The runtime binds them from the session.
SCOPE_ARG_KEYS: FrozenSet[str] = frozenset({"patient_id", "tenant_id", "session_id", "doctor_id"})


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

ToolId = Literal[
    # Retrieval
    "retrieve_session",
    "retrieve_structured",          # replaces retrieve_labs; kind= selects sub-type
    "retrieve_source_chunks",       # fetch raw chunk spans for grounding (§12.7)
    "get_patient_profile",          # session snapshot summary (§12.7)
    "retrieve_docs",
    "retrieve_visits",
    "retrieve_for_candidates",
    # Ingest
    "ingest_delta",
    # Compare
    "compare_findings",
    # Note job
    "generate_note",
    # Safety — split from safety_check (§12.7)
    "check_med_conflicts",
    "check_dosage",
    "check_metric_alerts",
    # Compute — LLM-free, planner-allowlisted (#85)
    "normalize_units",
    "compute_trend",
    "compute_delta",
]

ToolCategory = Literal["retrieval", "ingest", "compare", "note", "safety", "compute"]

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

# bounded_agent renamed to planning_agent in 1.2 (§12.5).
ToolCaller = Literal["lane_b_stage", "fixed_executor", "planning_agent"]

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

# Evidence lifecycle per citation (§12.2).
EvidenceState = Literal["received", "materialized", "validated", "authorized"]

TOOL_IDS: Tuple[str, ...] = get_args(ToolId)
TOOL_CATEGORIES: Tuple[str, ...] = get_args(ToolCategory)
LANE_B_STAGES: Tuple[str, ...] = get_args(LaneBStage)
TOOL_CALLERS: Tuple[str, ...] = get_args(ToolCaller)
TOOL_WRITES: Tuple[str, ...] = get_args(ToolWrites)
SOURCE_KINDS: Tuple[str, ...] = get_args(SourceKind)
EVIDENCE_STATES: Tuple[str, ...] = get_args(EvidenceState)


# ---------------------------------------------------------------------------
# Registry specs
# ---------------------------------------------------------------------------

class ToolSpec(TypedDict):
    category: ToolCategory
    assist_callable: bool                   # fixed assist workflows / jobs may call it
    planner_allowlisted: bool               # planning_agent may call it (renamed from agent_allowlisted)
    lane_b_stages: Tuple[LaneBStage, ...]   # compile stages allowed to call it; () = not a compile step
    writes: ToolWrites
    requires_citations: bool                # an ok result must carry at least one citation


TOOL_SPECS: Dict[str, ToolSpec] = {
    "retrieve_session": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_structured": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_source_chunks": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "get_patient_profile": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_docs": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_visits": ToolSpec(
        category="retrieval", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "retrieve_for_candidates": ToolSpec(
        category="retrieval", assist_callable=False, planner_allowlisted=False,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "ingest_delta": ToolSpec(
        category="ingest", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("ingest_delta",), writes="session_scratch", requires_citations=False,
    ),
    "compare_findings": ToolSpec(
        category="compare", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=("enrich",), writes="none", requires_citations=True,
    ),
    "generate_note": ToolSpec(
        category="note", assist_callable=True, planner_allowlisted=False,
        lane_b_stages=(), writes="session_draft", requires_citations=False,
    ),
    "check_med_conflicts": ToolSpec(
        category="safety", assist_callable=True, planner_allowlisted=False,
        lane_b_stages=("safety_and_validate",), writes="none", requires_citations=False,
    ),
    "check_dosage": ToolSpec(
        category="safety", assist_callable=True, planner_allowlisted=False,
        lane_b_stages=("safety_and_validate",), writes="none", requires_citations=False,
    ),
    "check_metric_alerts": ToolSpec(
        category="safety", assist_callable=True, planner_allowlisted=False,
        lane_b_stages=("safety_and_validate",), writes="none", requires_citations=False,
    ),
    # Compute tools are LLM-free, deterministic, and planner-allowlisted (#85).
    "normalize_units": ToolSpec(
        category="compute", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=(), writes="none", requires_citations=False,
    ),
    "compute_trend": ToolSpec(
        category="compute", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=(), writes="none", requires_citations=False,
    ),
    "compute_delta": ToolSpec(
        category="compute", assist_callable=True, planner_allowlisted=True,
        lane_b_stages=(), writes="none", requires_citations=False,
    ),
}

PLANNER_ALLOWLIST: FrozenSet[str] = frozenset(
    tool_id for tool_id, spec in TOOL_SPECS.items() if spec["planner_allowlisted"]
)

# Backwards-compat alias — tests that already reference AGENT_ALLOWLIST still pass.
AGENT_ALLOWLIST = PLANNER_ALLOWLIST


# ---------------------------------------------------------------------------
# Citation and claim types
# ---------------------------------------------------------------------------

class DocumentCitationLocator(TypedDict):
    """A span in a document, with character offsets on a 1-indexed page."""
    page: int
    char_start: int
    char_end: int


class TranscriptCitationLocator(TypedDict):
    """A span within one transcript segment, expressed in seconds."""
    segment_id: str
    t_start: float
    t_end: float


CitationLocator = Union[DocumentCitationLocator, TranscriptCitationLocator]


class Citation(TypedDict):
    source_kind: SourceKind
    source_id: str                  # doc id, lab row key, visit id, transcript segment id
    snippet: Optional[str]
    observed_at: Optional[str]      # ISO date of the underlying fact (lab draw, visit)
    received_at: str                # ISO-8601 when the source entered the system (§12.2)
    evidence_state: EvidenceState   # lifecycle state at query time (§12.2)
    locator: Optional[CitationLocator]       # span within the source (§12.7)
    score: Optional[float]


class Derivation(TypedDict):
    """Compute receipt attached to a derived claim (§12.7).

    The strict grounding validator re-checks the derived value against this
    receipt before allowing the claim to render.
    """
    operation: str                  # compute tool id that produced the value
    input_citation_ids: List[str]   # source_ids of the input citations
    receipt_id: str                 # ToolInvocationReceipt.invocation_id


class Claim(TypedDict):
    """Structured claim emitted by synthesis; validated before rendering (§12.7)."""
    claim_id: str
    text: str
    claim_type: str
    value: Optional[Any]
    unit: Optional[str]
    date: Optional[str]
    negated: Optional[bool]
    citation_ids: List[str]         # source_ids from the citation list
    derivation: Optional[Derivation]  # present only for computed values
    evidence_state: EvidenceState    # assigned from validated evidence before rendering


# ---------------------------------------------------------------------------
# Invocation receipt
# ---------------------------------------------------------------------------

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
    validator's job (grounding/validator.py in Phase 1).
    """
    if not isinstance(result, dict):
        return ["tool result must be an object"]
    missing = set(ToolResult.__annotations__) - set(result)
    if missing:
        return [f"missing fields: {sorted(missing)}"]

    spec = TOOL_SPECS.get(result["tool_id"])
    if spec is None:
        return [f"unknown tool {result['tool_id']!r}"]

    errors: List[str] = []
    if not isinstance(result["ok"], bool):
        errors.append("ok must be bool")
    if not isinstance(result["data"], dict):
        errors.append("data must be an object")

    citations = result["citations"]
    if not isinstance(citations, list):
        errors.append("citations must be a list")
        citations = []
    for index, citation in enumerate(citations):
        errors.extend(_citation_errors(citation, index))

    if result["ok"] is True and spec["requires_citations"] and not citations:
        errors.append(f"{result['tool_id']} returned ok without citations (ungrounded)")
    if result["ok"] is False and not isinstance(result["error"], str):
        errors.append("failed result must carry an error string")
    if result["ok"] is True and result["error"] is not None:
        errors.append("successful result must have error=null")

    errors.extend(_receipt_errors(result["receipt"], result["tool_id"], result["ok"], result["error"]))

    return errors


def _citation_errors(citation: Any, index: int) -> List[str]:
    prefix = f"citations[{index}]"
    if not isinstance(citation, dict):
        return [f"{prefix} must be an object"]
    missing = set(Citation.__annotations__) - set(citation)
    if missing:
        return [f"{prefix} missing fields: {sorted(missing)}"]

    errors: List[str] = []
    if citation["source_kind"] not in SOURCE_KINDS:
        errors.append(f"{prefix}.source_kind must be in contract")
    if not isinstance(citation["source_id"], str) or not citation["source_id"]:
        errors.append(f"{prefix}.source_id must be a non-empty string")
    for name in ("snippet", "observed_at"):
        if citation[name] is not None and not isinstance(citation[name], str):
            errors.append(f"{prefix}.{name} must be a string or null")
    if not isinstance(citation["received_at"], str) or not citation["received_at"]:
        errors.append(f"{prefix}.received_at must be a non-empty ISO-8601 string")
    if citation["evidence_state"] not in EVIDENCE_STATES:
        errors.append(f"{prefix}.evidence_state must be in contract")
    if citation["score"] is not None and (
        not isinstance(citation["score"], (int, float)) or isinstance(citation["score"], bool)
    ):
        errors.append(f"{prefix}.score must be a number or null")
    errors.extend(_locator_errors(citation["locator"], citation["source_kind"], prefix))
    return errors


def _locator_errors(locator: Any, source_kind: Any, prefix: str) -> List[str]:
    document_kinds = {"uploaded_doc", "prior_docs"}
    if source_kind == "session_transcript":
        if not isinstance(locator, dict) or set(locator) != set(TranscriptCitationLocator.__annotations__):
            return [f"{prefix}.locator must be a transcript locator"]
        if not isinstance(locator["segment_id"], str) or not locator["segment_id"]:
            return [f"{prefix}.locator.segment_id must be a non-empty string"]
        if not all(
            isinstance(locator[name], (int, float)) and not isinstance(locator[name], bool)
            for name in ("t_start", "t_end")
        ) or locator["t_start"] > locator["t_end"]:
            return [f"{prefix}.locator transcript offsets must be ordered numbers"]
        return []
    if source_kind in document_kinds:
        if not isinstance(locator, dict) or set(locator) != set(DocumentCitationLocator.__annotations__):
            return [f"{prefix}.locator must be a document locator"]
        if not all(isinstance(locator[name], int) and not isinstance(locator[name], bool) for name in ("page", "char_start", "char_end")):
            return [f"{prefix}.locator document offsets must be integers"]
        if locator["page"] < 1 or locator["char_start"] < 0 or locator["char_start"] > locator["char_end"]:
            return [f"{prefix}.locator document offsets must be ordered and non-negative"]
        return []
    return [] if locator is None else [f"{prefix}.locator is only valid for document or transcript sources"]


def _receipt_errors(receipt: Any, result_tool_id: Any, result_ok: Any, result_error: Any) -> List[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    missing = set(ToolInvocationReceipt.__annotations__) - set(receipt)
    if missing:
        return [f"receipt missing fields: {sorted(missing)}"]

    errors: List[str] = []
    if receipt["contract_version"] != RUNTIME_CONTRACT_VERSION:
        errors.append("receipt.contract_version must match runtime contract")
    for name in ("invocation_id", "session_id", "tool_version", "caller_ref", "args_hash", "created_at"):
        if not isinstance(receipt[name], str) or not receipt[name]:
            errors.append(f"receipt.{name} must be a non-empty string")
    if receipt["tool_id"] != result_tool_id:
        errors.append("receipt.tool_id must match result.tool_id")
    if receipt["caller"] not in TOOL_CALLERS:
        errors.append("receipt.caller must be in contract")
    if not isinstance(receipt["ok"], bool):
        errors.append("receipt.ok must be bool")
    elif receipt["ok"] != result_ok:
        errors.append("receipt.ok must match result.ok")
    if receipt["error"] is not None and not isinstance(receipt["error"], str):
        errors.append("receipt.error must be a string or null")
    elif receipt["error"] != result_error:
        errors.append("receipt.error must match result.error")
    if not isinstance(receipt["cache_hit"], bool):
        errors.append("receipt.cache_hit must be bool")
    if not isinstance(receipt["latency_ms"], (int, float)) or isinstance(receipt["latency_ms"], bool) or receipt["latency_ms"] < 0:
        errors.append("receipt.latency_ms must be a non-negative number")
    if not isinstance(receipt["source_refs"], list) or not all(isinstance(ref, str) for ref in receipt["source_refs"]):
        errors.append("receipt.source_refs must be a list of strings")
    return errors
