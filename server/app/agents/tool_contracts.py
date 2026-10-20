"""
Shared tool registry contract — v1.2 (agent refactor Phase 1A, #50).

One capability, three callers: Lane B compile stages, fixed assist workflows,
and the planning agent call the same tool ids through one registry, so ranking,
citation rules, and receipts cannot drift. Patient / clinician scope is injected
by the runtime from the verified session, never supplied by a model. Types,
validators, and the evidence-bundle append rules only; the registry
implementation lands in Phase 1 under server/app/agents/tools/.

Semantics and change control: docs/copilot_runtime_contract.md §6 and §10.
Type catalogue: docs/design/medscribe-runtime-sdd.md Appendix A.

Changes from 1.1:
- Tool ids v2: retrieve_labs -> retrieve_structured; safety_check split into
  check_med_conflicts / check_dosage / check_metric_alerts; get_patient_profile
  and retrieve_source_chunks added; compute tools added (§12.7).
- Citation gains citation_id, received_at, evidence_state, locator (§12.2).
- CitationLocator is a union tagged on kind: DocumentSpan | TranscriptSpan | RowRef (G4).
- SourceKind names what a source is, never when it arrived, so citation_id
  ({source_kind}:{source_id}) is stable across sessions.
- Claim and Derivation types added for the strict grounding validator (§12.7);
  both reference citation_ids.
- EvidenceBundle, CoverageBanner, RequirementOutcome: the one per-request
  evidence accumulator (SDD A.2).
- ToolCaller: bounded_agent -> planning_agent (§12.5).
- ingest_delta is a Lane B stage only; intake is gateway-owned.
- NOT_COVERED_ERROR added for safety tools that do not cover the requested check.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, Union, get_args

logger = logging.getLogger(__name__)

RUNTIME_CONTRACT_VERSION = "1.2"

# A retrieval that finds nothing grounded returns ok=False with this error,
# so the answer layer says "no documented value" instead of guessing.
NO_SOURCE_ERROR = "no_source"

# Safety tools return this error when the requested check is outside the
# current rule set's coverage (e.g. a drug not in the formulary table).
NOT_COVERED_ERROR = "not_covered"

# Keys a model may never put in tool args. The runtime binds them from the
# verified gateway token. tenant_id is not a runtime scope (multi-tenancy is a
# non-goal); it stays here only so a model can never supply one.
SCOPE_ARG_KEYS: FrozenSet[str] = frozenset({"patient_id", "clinician_id", "session_id", "tenant_id"})


class ContractViolationError(ValueError):
    """A runtime contract object or operation broke the 1.2 contract.

    Subclasses ValueError so callers that already catch ValueError on bad
    enum input keep working.
    """


class BundleClosedError(ContractViolationError):
    """An append was attempted on an EvidenceBundle after it was closed."""


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

# What a source is, never when or where it arrived. Whether a document came in
# this session is read from ingest_documents.session_id, so the same document
# has one citation_id whenever it is cited.
SourceKind = Literal[
    "session_transcript",
    "session_draft",
    "patient_snapshot",
    "document",
    "observation",
    "visit",
]

# Evidence lifecycle per citation (§12.2).
EvidenceState = Literal["received", "materialized", "validated", "authorized"]

# Ingest readiness of a document, ordered (SQL ingest_level, SDD C.2).
IngestLevel = Literal["received", "described", "indexed", "facts"]

# Outcome of one document requirement at barrier release (SQL requirement_status).
RequirementStatus = Literal["met", "unmet_terminal", "pending"]

# Why a document stopped short of its need (ingest_document_readiness.failure_code).
FailureCode = Literal["unreadable_file", "ocr_failed", "extraction_failed", "timeout"]

TOOL_IDS: Tuple[str, ...] = get_args(ToolId)
TOOL_CATEGORIES: Tuple[str, ...] = get_args(ToolCategory)
LANE_B_STAGES: Tuple[str, ...] = get_args(LaneBStage)
TOOL_CALLERS: Tuple[str, ...] = get_args(ToolCaller)
TOOL_WRITES: Tuple[str, ...] = get_args(ToolWrites)
SOURCE_KINDS: Tuple[str, ...] = get_args(SourceKind)
EVIDENCE_STATES: Tuple[str, ...] = get_args(EvidenceState)
INGEST_LEVELS: Tuple[str, ...] = get_args(IngestLevel)
REQUIREMENT_STATUSES: Tuple[str, ...] = get_args(RequirementStatus)
FAILURE_CODES: Tuple[str, ...] = get_args(FailureCode)


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
    # Intake is gateway-owned (#93); ingest_delta is a Lane B stage only.
    "ingest_delta": ToolSpec(
        category="ingest", assist_callable=False, planner_allowlisted=False,
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


# ---------------------------------------------------------------------------
# Citation and claim types
# ---------------------------------------------------------------------------

class DocumentSpan(TypedDict):
    """A character span on a 1-indexed page of one chunk of a document."""
    kind: Literal["document_span"]
    doc_id: str
    chunk_id: str
    page: int
    char_start: int
    char_end: int


class TranscriptSpan(TypedDict):
    """A span within one transcript segment, expressed in seconds."""
    kind: Literal["transcript_span"]
    segment_id: str
    t_start: float
    t_end: float


class RowRef(TypedDict):
    """A row (and optionally one column) of a structured table."""
    kind: Literal["row_ref"]
    table: str
    row_id: str
    column: Optional[str]           # null = the whole row is the evidence


CitationLocator = Union[DocumentSpan, TranscriptSpan, RowRef]

# The locator shape each source kind takes; kinds not listed take no locator.
LOCATOR_KIND_BY_SOURCE: Dict[str, str] = {
    "document": "document_span",
    "session_transcript": "transcript_span",
    "observation": "row_ref",
    "visit": "row_ref",
}

_LOCATOR_SHAPES: Dict[str, type] = {
    "document_span": DocumentSpan,
    "transcript_span": TranscriptSpan,
    "row_ref": RowRef,
}


class Citation(TypedDict):
    citation_id: str                # make_citation_id(): names the cited span, not the source (SDD A.2)
    source_kind: SourceKind
    source_id: str                  # doc_id, observation id, visit id, transcript segment id
    snippet: Optional[str]
    observed_at: Optional[str]      # ISO date of the underlying fact (lab draw, visit)
    received_at: str                # ISO-8601 when the source entered the system (§12.2)
    evidence_state: EvidenceState   # lifecycle state at query time (§12.2)
    locator: Optional[CitationLocator]  # shape follows source_kind (LOCATOR_KIND_BY_SOURCE)
    score: Optional[float]


def _locator_key(locator: Dict[str, Any]) -> str:
    """The span part of a citation id; transcript times are integer ms, never floats."""
    kind = locator["kind"]
    if kind == "document_span":
        return f"{locator['chunk_id']}:{locator['char_start']}-{locator['char_end']}"
    if kind == "transcript_span":
        t_start_ms = int(round(float(locator["t_start"]) * 1000))
        t_end_ms = int(round(float(locator["t_end"]) * 1000))
        return f"{locator['segment_id']}:{t_start_ms}-{t_end_ms}"
    column = locator.get("column") or ""
    return f"{locator['table']}/{locator['row_id']}/{column}"


def make_citation_id(
    source_kind: str,
    source_id: str,
    locator: Optional[CitationLocator] = None,
) -> str:
    """Build the one citation id for a cited span (SDD A.2, F.4 P1).

    Kinds with a locator get ``{source_kind}:{source_id}#{locator_key}``, so two
    spans of one document get two ids. Kinds without one get
    ``{source_kind}:{source_id}``.

    Raises:
        ContractViolationError: unknown source_kind, empty source_id, or a
        locator missing or present against LOCATOR_KIND_BY_SOURCE.
    """
    if source_kind not in SOURCE_KINDS:
        raise ContractViolationError(
            f"source_kind={source_kind!r} not in contract; expected one of {SOURCE_KINDS}"
        )
    if not isinstance(source_id, str) or not source_id:
        raise ContractViolationError(f"source_id={source_id!r}; expected a non-empty string")

    expected_kind = LOCATOR_KIND_BY_SOURCE.get(source_kind)
    if expected_kind is None:
        if locator is not None:
            raise ContractViolationError(
                f"locator={locator!r} given for source_kind={source_kind!r}; expected no locator"
            )
        return f"{source_kind}:{source_id}"

    errors = _locator_errors(locator, source_kind, source_id, "locator")
    if errors:
        raise ContractViolationError(
            f"cannot build citation_id for {source_kind}:{source_id}: {'; '.join(errors)}"
        )
    return f"{source_kind}:{source_id}#{_locator_key(locator)}"  # type: ignore[arg-type]


class Derivation(TypedDict):
    """Compute receipt attached to a derived claim (§12.7).

    The strict grounding validator re-checks the derived value against this
    receipt before allowing the claim to render.
    """
    operation: str                  # compute tool id that produced the value
    input_citation_ids: List[str]   # Citation.citation_id of each input
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
    citation_ids: List[str]         # Citation.citation_id values
    derivation: Optional[Derivation]  # present only for computed values
    evidence_state: EvidenceState    # weakest state among the claim's citations


def claim_citation_closure(claims: List[Dict[str, Any]]) -> FrozenSet[str]:
    """Every citation_id the claims depend on, including derivation inputs.

    AssistAnswer.cited must cover exactly this set.
    """
    closure: set[str] = set()
    for claim in claims:
        closure.update(claim.get("citation_ids") or [])
        derivation = claim.get("derivation")
        if isinstance(derivation, dict):
            closure.update(derivation.get("input_citation_ids") or [])
    return frozenset(closure)


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
    error: Optional[str]            # equals ToolResult.error; read when the receipt is inspected alone
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
# Evidence bundle (SDD A.2)
# ---------------------------------------------------------------------------

class RequirementOutcome(TypedDict):
    """What one referenced document needed, and whether it got there by barrier release."""
    doc_id: str
    need: IngestLevel
    status: RequirementStatus
    failure_code: Optional[FailureCode]  # set only when status == "unmet_terminal"


class CoverageBanner(TypedDict):
    """What the answer could and could not see; the answer's coverage line words it."""
    requirements: List[RequirementOutcome]
    unreferenced_inflight_doc_ids: List[str]  # in flight but not referenced by the ask
    partial_sources: List[str]                # source keys that answered with partial data


class EvidenceBundle(TypedDict):
    """The one per-request evidence accumulator. Append-only; closed before synthesis.

    The request cutoff lives on AssistRequestContext.watermarks and receipt ids
    are read from results[].receipt; neither is copied here.
    """
    bundle_id: str
    results: List[ToolResult]
    citations: Dict[str, Citation]  # keyed by citation_id; a source cited twice appears once
    sources_checked: List[str]      # source_check_key(tool_id, args_hash) of every run
    coverage: CoverageBanner
    closed: bool


def source_check_key(tool_id: str, args_hash: str) -> str:
    """The one encoding of a tool run used for dedupe and plan validation."""
    if tool_id not in TOOL_SPECS:
        raise ContractViolationError(f"tool_id={tool_id!r} not in TOOL_SPECS")
    if not isinstance(args_hash, str) or not args_hash:
        raise ContractViolationError(f"args_hash={args_hash!r}; expected a non-empty string")
    return f"{tool_id}:{args_hash}"


def empty_coverage() -> CoverageBanner:
    return CoverageBanner(requirements=[], unreferenced_inflight_doc_ids=[], partial_sources=[])


def new_bundle(bundle_id: str) -> EvidenceBundle:
    """Open an empty bundle for one request.

    Raises:
        ContractViolationError: bundle_id is empty or not a string.
    """
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ContractViolationError(f"bundle_id={bundle_id!r}; expected a non-empty string")
    logger.debug("evidence bundle opened bundle_id=%s", bundle_id)
    return EvidenceBundle(
        bundle_id=bundle_id,
        results=[],
        citations={},
        sources_checked=[],
        coverage=empty_coverage(),
        closed=False,
    )


def append_result(bundle: EvidenceBundle, result: Dict[str, Any]) -> bool:
    """Append one tool result to an open bundle.

    Returns True when appended. Returns False, and logs a warning, when the same
    tool and args already ran in this request: the earlier result stands and
    the duplicate is dropped so the caller can see it was not used.

    Raises:
        BundleClosedError: the bundle is closed.
        ContractViolationError: the result fails validate_tool_result().
    """
    if bundle["closed"]:
        raise BundleClosedError(
            f"bundle_id={bundle['bundle_id']!r} is closed; appends after close are not allowed"
        )
    errors = validate_tool_result(result)
    if errors:
        raise ContractViolationError(
            f"bundle_id={bundle['bundle_id']!r} rejected an invalid tool result: {errors}"
        )

    receipt = result["receipt"]
    key = source_check_key(result["tool_id"], receipt["args_hash"])
    if key in bundle["sources_checked"]:
        logger.warning(
            "duplicate tool run dropped bundle_id=%s tool_id=%s invocation_id=%s; "
            "expected one run per tool and args, keeping the first",
            bundle["bundle_id"], result["tool_id"], receipt["invocation_id"],
        )
        return False

    bundle["results"].append(result)  # type: ignore[arg-type]
    bundle["sources_checked"].append(key)
    for citation in result["citations"]:
        bundle["citations"].setdefault(citation["citation_id"], citation)
    return True


def close_bundle(bundle: EvidenceBundle, coverage: CoverageBanner) -> EvidenceBundle:
    """Set coverage and close the bundle. Closing is a hard edge.

    Raises:
        BundleClosedError: the bundle is already closed.
        ContractViolationError: coverage fails validate_coverage().
    """
    if bundle["closed"]:
        raise BundleClosedError(f"bundle_id={bundle['bundle_id']!r} is already closed")
    errors = validate_coverage(coverage)
    if errors:
        raise ContractViolationError(
            f"bundle_id={bundle['bundle_id']!r} rejected invalid coverage: {errors}"
        )
    bundle["coverage"] = coverage
    bundle["closed"] = True
    logger.info(
        "evidence bundle closed bundle_id=%s results=%d citations=%d requirements=%d",
        bundle["bundle_id"], len(bundle["results"]), len(bundle["citations"]),
        len(coverage["requirements"]),
    )
    return bundle


def bundle_receipt_ids(bundle: EvidenceBundle) -> List[str]:
    """Receipt ids of every result in the bundle, in append order."""
    return [result["receipt"]["invocation_id"] for result in bundle["results"]]


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
    elif isinstance(args, (list, tuple)):
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


def validate_tool_result(result: Any) -> List[str]:
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
        errors.extend(citation_errors(citation, f"citations[{index}]"))

    if result["ok"] is True and spec["requires_citations"] and not citations:
        errors.append(f"{result['tool_id']} returned ok without citations (ungrounded)")
    if result["ok"] is False and not isinstance(result["error"], str):
        errors.append("failed result must carry an error string")
    if result["ok"] is True and result["error"] is not None:
        errors.append("successful result must have error=null")

    errors.extend(_receipt_errors(result["receipt"], result["tool_id"], result["ok"], result["error"]))

    return errors


def citation_errors(citation: Any, prefix: str = "citation") -> List[str]:
    """Return violations for one Citation (empty list = valid)."""
    if not isinstance(citation, dict):
        return [f"{prefix} must be an object"]
    missing = set(Citation.__annotations__) - set(citation)
    if missing:
        return [f"{prefix} missing fields: {sorted(missing)}"]

    errors: List[str] = []
    source_kind, source_id = citation["source_kind"], citation["source_id"]
    if source_kind not in SOURCE_KINDS:
        errors.append(f"{prefix}.source_kind={source_kind!r} not in contract")
    locator_errors = _locator_errors(citation["locator"], source_kind, source_id, prefix)
    if not isinstance(source_id, str) or not source_id:
        errors.append(f"{prefix}.source_id must be a non-empty string")
    elif source_kind in SOURCE_KINDS and not locator_errors:
        expected_id = make_citation_id(source_kind, source_id, citation["locator"])
        if citation["citation_id"] != expected_id:
            errors.append(f"{prefix}.citation_id={citation['citation_id']!r}; expected {expected_id}")
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
    errors.extend(locator_errors)
    return errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _locator_errors(locator: Any, source_kind: Any, source_id: Any, prefix: str) -> List[str]:
    expected_kind = LOCATOR_KIND_BY_SOURCE.get(source_kind)
    if expected_kind is None:
        return [] if locator is None else [f"{prefix}.locator must be null for source_kind={source_kind!r}"]

    here = f"{prefix}.locator"
    if not isinstance(locator, dict) or locator.get("kind") != expected_kind:
        return [f"{here} must be a {expected_kind} for source_kind={source_kind!r}"]
    if set(locator) != set(_LOCATOR_SHAPES[expected_kind].__annotations__):
        return [f"{here} fields must be {sorted(_LOCATOR_SHAPES[expected_kind].__annotations__)}"]

    if expected_kind == "document_span":
        if locator["doc_id"] != source_id:
            return [f"{here}.doc_id={locator['doc_id']!r} must equal source_id={source_id!r}"]
        if not isinstance(locator["chunk_id"], str) or not locator["chunk_id"]:
            return [f"{here}.chunk_id must be a non-empty string"]
        if not all(_is_int(locator[name]) for name in ("page", "char_start", "char_end")):
            return [f"{here} document offsets must be integers"]
        if locator["page"] < 1 or locator["char_start"] < 0 or locator["char_start"] > locator["char_end"]:
            return [f"{here} document offsets must be ordered and non-negative"]
        return []

    if expected_kind == "transcript_span":
        if locator["segment_id"] != source_id:
            return [f"{here}.segment_id={locator['segment_id']!r} must equal source_id={source_id!r}"]
        if not all(_is_number(locator[name]) for name in ("t_start", "t_end")) or locator["t_start"] > locator["t_end"]:
            return [f"{here} transcript offsets must be ordered numbers"]
        return []

    # row_ref
    if not isinstance(locator["table"], str) or not locator["table"]:
        return [f"{here}.table must be a non-empty string"]
    if locator["row_id"] != source_id:
        return [f"{here}.row_id={locator['row_id']!r} must equal source_id={source_id!r}"]
    if locator["column"] is not None and (not isinstance(locator["column"], str) or not locator["column"]):
        return [f"{here}.column must be a non-empty string or null"]
    return []


def validate_coverage(coverage: Any) -> List[str]:
    """Return violations for a CoverageBanner (empty list = valid)."""
    if not isinstance(coverage, dict) or set(coverage) != set(CoverageBanner.__annotations__):
        return [f"coverage fields must be {sorted(CoverageBanner.__annotations__)}"]
    errors: List[str] = []
    for name in ("unreferenced_inflight_doc_ids", "partial_sources"):
        value = coverage[name]
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            errors.append(f"coverage.{name} must be a list of non-empty strings")
    requirements = coverage["requirements"]
    if not isinstance(requirements, list):
        return [*errors, "coverage.requirements must be a list"]
    seen: set[str] = set()
    for index, req in enumerate(requirements):
        prefix = f"coverage.requirements[{index}]"
        if not isinstance(req, dict) or set(req) != set(RequirementOutcome.__annotations__):
            errors.append(f"{prefix} fields must be {sorted(RequirementOutcome.__annotations__)}")
            continue
        if not isinstance(req["doc_id"], str) or not req["doc_id"]:
            errors.append(f"{prefix}.doc_id must be a non-empty string")
        elif req["doc_id"] in seen:
            errors.append(f"{prefix}.doc_id={req['doc_id']!r} is listed twice")
        else:
            seen.add(req["doc_id"])
        if req["need"] not in INGEST_LEVELS:
            errors.append(f"{prefix}.need={req['need']!r} not in {INGEST_LEVELS}")
        if req["status"] not in REQUIREMENT_STATUSES:
            errors.append(f"{prefix}.status={req['status']!r} not in {REQUIREMENT_STATUSES}")
        if req["status"] == "unmet_terminal":
            if req["failure_code"] not in FAILURE_CODES:
                errors.append(f"{prefix}.failure_code={req['failure_code']!r}; unmet_terminal needs one of {FAILURE_CODES}")
        elif req["failure_code"] is not None:
            errors.append(f"{prefix}.failure_code must be null unless status is unmet_terminal")
    return errors


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
