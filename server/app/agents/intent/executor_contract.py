"""
Executor contract — v1.2 (agent refactor Phase 1A, #50).

The request, routing, control, and output carriers of one assist request
(SDD Appendix A, families 1, 3, 4). The gate outputs addressee + task slots
(with sub_asks); dispatch_assist() picks the execution path from those slots
via a pure code table and returns one DispatchDecision (§12.4, G1).

- Fixed workflows where the evidence class is known and independent.
- Fan-out when multiple independent workflows fit within MAX_FANOUT_WORKFLOWS.
- Dependent or uncovered asks (rule 3) map to clarify and log needs_plan while
  the planner is deferred (SDD §9.2); the planning_agent value stays in the
  literal so the boundary is stable when #58 re-enters.
- clarify when scope is underspecified or sub-asks conflict.

A fixed workflow returns a closed WorkflowOutcome. A PlanRequest is the
immutable handoff to the planner; evidence goes by reference (EvidenceRef).

Provisional numbers are imported from agents/config.py so they live in one
config file and are not duplicated in contract types.

Semantics: docs/copilot_runtime_contract.md §2, §5, §12.4–12.5.

Changes from 1.1:
- DispatchValue added: silent | clarify | workflow | fanout | planning_agent.
- dispatch_assist(context, slots) -> DispatchDecision (§12.4 table, G1).
- AssistRequestContext + ReceiptWatermarks own request identity, cutoff, and
  deadline (G2).
- ClarifyKind / ScopeChoice / ClarifyRequest added (§12.4).
- WorkflowOutcome (Completed | ClarificationNeeded | PlanningNeeded),
  PlanRequest + EvidenceRef added; WorkflowState deleted.
- AssistAnswer + AnswerStatus added.
- Planner symbols (WorkerPlan, PlanTask, agent step budget) and the
  task_subtype-keyed executor tables are not part of 1.2; they return with #58.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, TypedDict, Union, get_args

from app.agents.config import MAX_FANOUT_WORKFLOWS, SUB_ASK_MIN_CONFIDENCE
from app.agents.intent.schemas import CHANNELS, EVIDENCE_CLASSES, Channel, SubAsk, sub_ask_errors
from app.agents.tool_contracts import (
    Citation,
    Claim,
    ContractViolationError,
    CoverageBanner,
    EvidenceBundle,
    bundle_receipt_ids,
    citation_errors,
    claim_citation_closure,
    find_scope_keys,
    validate_coverage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

DispatchValue = Literal["silent", "clarify", "workflow", "fanout", "planning_agent"]
DISPATCH_VALUES: Tuple[str, ...] = get_args(DispatchValue)

ClarifyKind = Literal["scope", "reading", "rephrase", "narrow"]
CLARIFY_KINDS: Tuple[str, ...] = get_args(ClarifyKind)

# What the physician picked on the still-processing card (G6). Durable
# notify-when-ready is deferred (SDD §9.2), so it is not a value here.
PhysicianChoice = Literal["processed_pages", "reask", "none"]
PHYSICIAN_CHOICES: Tuple[str, ...] = get_args(PhysicianChoice)

OutcomeKind = Literal["completed", "clarification_needed", "planning_needed"]
OUTCOME_KINDS: Tuple[str, ...] = get_args(OutcomeKind)

GroundingVerdict = Literal["render", "refuse"]
GROUNDING_VERDICTS: Tuple[str, ...] = get_args(GroundingVerdict)

AnswerStatus = Literal["answered", "refused", "clarifying", "still_processing"]
ANSWER_STATUSES: Tuple[str, ...] = get_args(AnswerStatus)

# Workflow ids are named after the evidence class, except these.
_WORKFLOW_ID_OVERRIDES: Dict[str, str] = {
    "general": "general_cascade",
    "note": "jobs",
    "session_control": "jobs",
}


def workflow_id_for(evidence_class: str) -> str:
    """Return the fixed workflow id that serves an evidence class.

    Raises:
        ContractViolationError: unknown class, or no_workflow (no fixed workflow).
    """
    if evidence_class not in EVIDENCE_CLASSES or evidence_class == "no_workflow":
        raise ContractViolationError(
            f"evidence_class={evidence_class!r}; expected a class with a fixed workflow"
        )
    return _WORKFLOW_ID_OVERRIDES.get(evidence_class, evidence_class)


# ---------------------------------------------------------------------------
# Family 1: request and routing
# ---------------------------------------------------------------------------

class ReceiptWatermarks(TypedDict):
    """What the request may see, captured once in the watermark transaction (#84)."""
    as_of_receipt: str              # ISO-8601 with offset, Postgres clock; retrieval cutoff
    snapshot_generation: int        # PatientContextSnapshot.snapshot_generation read by get_patient_profile
    transcript_stream_id: str       # last transcript stream entry visible to the request
    draft_version: Optional[str]    # null until the first compile of the session


class AssistRequestContext(TypedDict):
    """One per request; owns identity, cutoff, and deadline (G2).

    patient_id and clinician_id come from the verified gateway token. The
    registry injects them into tool args; this object is never serialized into
    a model prompt.
    """
    request_id: str
    session_id: str
    trace_id: str
    channel: Channel
    watermarks: ReceiptWatermarks
    deadline_at: str                # ISO-8601 with offset; absolute, never a remaining-ms value
    resumes_answer_id: Optional[str]  # the answer this request resumes (still-processing reask)
    patient_id: str
    clinician_id: str


class DispatchDecision(TypedDict):
    """The single route outcome; fills the merged route span (G1)."""
    dispatch: DispatchValue
    dispatch_rule: int              # 1..6, the first matching row of the table
    clarify_kind: Optional[ClarifyKind]  # set iff dispatch == "clarify"
    reason_codes: List[str]         # snake_case audit codes
    workflow_ids: List[str]         # one per workflow run, in sub-ask order; [] unless workflow/fanout


class ScopeChoice(TypedDict):
    """A single candidate scope offered to the physician (§12.4).

    Candidates come from the scope library only; the model cannot invent them.
    Personalized wording requires supporting_citation_ids from chart rows.
    """
    scope_id: str
    rank: int
    label: str
    supporting_citation_ids: List[str]  # citation_ids of chart rows; empty = generic
    expands_to: List[str]               # evidence classes / domains this choice resolves to


class ClarifyRequest(TypedDict):
    """Structured clarification request — no model-written free-text question (§12.4, §12.8 invariant 2)."""
    kind: ClarifyKind
    choices: List[ScopeChoice]
    allow_free_text: bool


# ---------------------------------------------------------------------------
# Family 3: control
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRef:
    """Evidence as it stood at handoff. The one justified copy of bundle ids:
    the bundle keeps growing, the ref does not."""
    bundle_id: str
    receipt_ids: Tuple[str, ...]
    citation_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_id, str) or not self.bundle_id:
            raise ContractViolationError(f"EvidenceRef.bundle_id={self.bundle_id!r}; expected a non-empty string")
        for name in ("receipt_ids", "citation_ids"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(isinstance(v, str) and v for v in value):
                raise ContractViolationError(
                    f"EvidenceRef.{name}={value!r}; expected a tuple of non-empty strings"
                )


def make_evidence_ref(bundle: EvidenceBundle) -> EvidenceRef:
    """Snapshot a bundle's receipt and citation ids for a handoff."""
    return EvidenceRef(
        bundle_id=bundle["bundle_id"],
        receipt_ids=tuple(bundle_receipt_ids(bundle)),
        citation_ids=tuple(bundle["citations"]),
    )


@dataclass(frozen=True)
class PlanRequest:
    """Immutable handoff from a fixed workflow to the planner.

    The planner runs in the same request as plan(context, plan_request): the
    cutoff and deadline_at are read from AssistRequestContext and
    sources_checked from the bundle that evidence_ref names, so none of them
    is copied here. Goal and scope may not change; scope carries no runtime
    scope keys.
    """
    workflow_id: str
    reason: str                     # why the fixed workflow could not finish
    goal: str
    scope: Tuple[SubAsk, ...]       # Stage B sub-asks, unchanged
    unmet_requirements: Tuple[str, ...]
    evidence_ref: EvidenceRef

    def __post_init__(self) -> None:
        for name in ("workflow_id", "reason", "goal"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ContractViolationError(f"PlanRequest.{name}={value!r}; expected a non-empty string")
        if not isinstance(self.scope, tuple) or not self.scope:
            raise ContractViolationError(f"PlanRequest.scope={self.scope!r}; expected a non-empty tuple of sub-asks")
        errors = sub_ask_errors(list(self.scope))
        if errors:
            raise ContractViolationError(f"PlanRequest.scope is not valid Stage B output: {errors}")
        scope_paths = find_scope_keys(list(self.scope))
        if scope_paths:
            raise ContractViolationError(
                f"PlanRequest.scope carries runtime scope keys {scope_paths}; scope keys are injected, never handed off"
            )
        if not isinstance(self.unmet_requirements, tuple) or not self.unmet_requirements or not all(
            isinstance(r, str) and r for r in self.unmet_requirements
        ):
            raise ContractViolationError(
                f"PlanRequest.unmet_requirements={self.unmet_requirements!r}; "
                "expected a non-empty tuple of non-empty strings (nothing unmet means Completed)"
            )
        if not isinstance(self.evidence_ref, EvidenceRef):
            raise ContractViolationError(
                f"PlanRequest.evidence_ref={type(self.evidence_ref).__name__}; expected EvidenceRef"
            )


class Completed(TypedDict):
    kind: Literal["completed"]
    bundle: EvidenceBundle


class ClarificationNeeded(TypedDict):
    kind: Literal["clarification_needed"]
    clarify: ClarifyRequest


class PlanningNeeded(TypedDict):
    kind: Literal["planning_needed"]
    plan_request: PlanRequest


# Closed union: every fixed workflow returns exactly one of these.
WorkflowOutcome = Union[Completed, ClarificationNeeded, PlanningNeeded]

# The payload field each outcome kind carries.
OUTCOME_PAYLOAD: Dict[str, str] = {
    "completed": "bundle",
    "clarification_needed": "clarify",
    "planning_needed": "plan_request",
}


def validate_workflow_outcome(outcome: Any) -> List[str]:
    """Return violations for a WorkflowOutcome (empty list = valid)."""
    if not isinstance(outcome, dict):
        return ["workflow outcome must be an object"]
    kind = outcome.get("kind")
    if kind not in OUTCOME_KINDS:
        return [f"outcome.kind={kind!r} not in {OUTCOME_KINDS}"]
    payload_key = OUTCOME_PAYLOAD[kind]
    if set(outcome) != {"kind", payload_key}:
        return [f"outcome kind={kind!r} must carry exactly ['kind', {payload_key!r}], got {sorted(outcome)}"]
    payload = outcome[payload_key]
    if kind == "completed":
        if not isinstance(payload, dict) or set(payload) != set(EvidenceBundle.__annotations__):
            return ["completed outcome must carry an EvidenceBundle"]
        return []
    if kind == "clarification_needed":
        return validate_clarify_request(payload)
    return [] if isinstance(payload, PlanRequest) else ["planning_needed outcome must carry a PlanRequest"]


def validate_clarify_request(clarify: Any) -> List[str]:
    """Return violations for a ClarifyRequest (empty list = valid)."""
    if not isinstance(clarify, dict) or set(clarify) != set(ClarifyRequest.__annotations__):
        return [f"clarify fields must be {sorted(ClarifyRequest.__annotations__)}"]
    errors: List[str] = []
    if clarify["kind"] not in CLARIFY_KINDS:
        errors.append(f"clarify.kind={clarify['kind']!r} not in {CLARIFY_KINDS}")
    if not isinstance(clarify["allow_free_text"], bool):
        errors.append("clarify.allow_free_text must be bool")
    if not isinstance(clarify["choices"], list):
        return [*errors, "clarify.choices must be a list"]
    for index, choice in enumerate(clarify["choices"]):
        prefix = f"clarify.choices[{index}]"
        if not isinstance(choice, dict) or set(choice) != set(ScopeChoice.__annotations__):
            errors.append(f"{prefix} fields must be {sorted(ScopeChoice.__annotations__)}")
            continue
        for name in ("scope_id", "label"):
            if not isinstance(choice[name], str) or not choice[name]:
                errors.append(f"{prefix}.{name} must be a non-empty string")
        if not isinstance(choice["rank"], int) or isinstance(choice["rank"], bool) or choice["rank"] < 1:
            errors.append(f"{prefix}.rank must be an integer >= 1")
        for name in ("supporting_citation_ids", "expands_to"):
            if not isinstance(choice[name], list) or not all(isinstance(v, str) and v for v in choice[name]):
                errors.append(f"{prefix}.{name} must be a list of non-empty strings")
    return errors


# ---------------------------------------------------------------------------
# Family 4: output
# ---------------------------------------------------------------------------

class GroundingReport(TypedDict):
    """Post-hoc check before an assist answer renders.

    Groundedness means citation correctness, not citation presence: each
    patient-fact claim's citation must resolve to a real source that contains
    the stated value.
    """
    claims_checked: int
    unsupported_claim_ids: List[str]
    verdict: GroundingVerdict


class AssistAnswer(TypedDict):
    """What the UI renders and what follow-ups and replay read. Session-durable."""
    answer_id: str
    request_id: str
    session_id: str
    status: AnswerStatus
    claims: List[Claim]
    cited: List[Citation]           # exactly the citations the claims close over
    bundle_ref: Optional[str]       # EvidenceBundle.bundle_id; null only when clarifying before any retrieval
    grounding: Optional[GroundingReport]  # null for clarifying / still_processing
    clarify: Optional[ClarifyRequest]     # set iff status == "clarifying"
    coverage: Optional[CoverageBanner]    # set for still_processing; else the closed bundle's coverage
    watermarks: ReceiptWatermarks   # copied from the context; the answer's cutoff
    resumes_answer_id: Optional[str]
    created_at: str                 # ISO-8601


def grounding_verdict(unsupported_claim_ids: Sequence[str]) -> GroundingVerdict:
    """Any unsupported claim blocks rendering; the executor refuses or re-drafts."""
    return "refuse" if unsupported_claim_ids else "render"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_aware_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp that carries an offset; None if it does not."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _optional_id_errors(value: Any, name: str) -> List[str]:
    if value is not None and (not isinstance(value, str) or not value):
        return [f"{name}={value!r}; expected a non-empty string or null"]
    return []


def validate_watermarks(watermarks: Any, prefix: str = "watermarks") -> List[str]:
    """Return violations for ReceiptWatermarks (empty list = valid)."""
    if not isinstance(watermarks, dict) or set(watermarks) != set(ReceiptWatermarks.__annotations__):
        return [f"{prefix} fields must be {sorted(ReceiptWatermarks.__annotations__)}"]
    errors: List[str] = []
    if _is_aware_iso(watermarks["as_of_receipt"]) is None:
        errors.append(f"{prefix}.as_of_receipt={watermarks['as_of_receipt']!r}; expected ISO-8601 with offset")
    generation = watermarks["snapshot_generation"]
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        errors.append(f"{prefix}.snapshot_generation={generation!r}; expected an integer >= 0")
    if not isinstance(watermarks["transcript_stream_id"], str) or not watermarks["transcript_stream_id"]:
        errors.append(f"{prefix}.transcript_stream_id must be a non-empty string")
    errors.extend(_optional_id_errors(watermarks["draft_version"], f"{prefix}.draft_version"))
    return errors


def validate_request_context(context: Any) -> List[str]:
    """Return violations for an AssistRequestContext (empty list = valid)."""
    if not isinstance(context, dict):
        return ["request context must be an object"]
    missing = set(AssistRequestContext.__annotations__) - set(context)
    if missing:
        return [f"request context missing fields: {sorted(missing)}"]
    unknown = set(context) - set(AssistRequestContext.__annotations__)
    errors: List[str] = [f"request context has unknown fields: {sorted(unknown)}"] if unknown else []

    for name in ("request_id", "session_id", "trace_id", "patient_id", "clinician_id"):
        if not isinstance(context[name], str) or not context[name]:
            errors.append(f"context.{name}={context[name]!r}; expected a non-empty string")
    if context["channel"] not in CHANNELS:
        errors.append(f"context.channel={context['channel']!r} not in {CHANNELS}")
    errors.extend(_optional_id_errors(context["resumes_answer_id"], "context.resumes_answer_id"))
    errors.extend(validate_watermarks(context["watermarks"], "context.watermarks"))

    deadline = _is_aware_iso(context["deadline_at"])
    if deadline is None:
        errors.append(f"context.deadline_at={context['deadline_at']!r}; expected ISO-8601 with offset")
    elif isinstance(context["watermarks"], dict):
        cutoff = _is_aware_iso(context["watermarks"].get("as_of_receipt"))
        if cutoff is not None and deadline <= cutoff:
            errors.append("context.deadline_at must be later than watermarks.as_of_receipt")
    return errors


def validate_assist_answer(answer: Any) -> List[str]:
    """Return violations for an AssistAnswer (empty list = valid).

    Enforces the closure rule: cited holds exactly the citations the claims
    and their derivations reference, each once.
    """
    if not isinstance(answer, dict):
        return ["answer must be an object"]
    missing = set(AssistAnswer.__annotations__) - set(answer)
    if missing:
        return [f"answer missing fields: {sorted(missing)}"]

    errors = _answer_identity_errors(answer)
    if answer["status"] not in ANSWER_STATUSES:
        return [*errors, f"answer.status={answer['status']!r} not in {ANSWER_STATUSES}"]
    return [*errors, *_answer_citation_errors(answer), *_answer_status_errors(answer)]


def _answer_identity_errors(answer: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for name in ("answer_id", "request_id", "session_id"):
        if not isinstance(answer[name], str) or not answer[name]:
            errors.append(f"answer.{name} must be a non-empty string")
    if _is_aware_iso(answer["created_at"]) is None:
        errors.append(f"answer.created_at={answer['created_at']!r}; expected ISO-8601 with offset")
    errors.extend(_optional_id_errors(answer["resumes_answer_id"], "answer.resumes_answer_id"))
    if answer["resumes_answer_id"] is not None and answer["resumes_answer_id"] == answer["answer_id"]:
        errors.append("answer.resumes_answer_id must not equal answer_id")
    errors.extend(validate_watermarks(answer["watermarks"], "answer.watermarks"))
    return errors


def _answer_citation_errors(answer: Dict[str, Any]) -> List[str]:
    claims, cited = answer["claims"], answer["cited"]
    if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
        return ["answer.claims must be a list of claims"]
    if not isinstance(cited, list):
        return ["answer.cited must be a list"]
    errors: List[str] = []
    for index, citation in enumerate(cited):
        errors.extend(citation_errors(citation, f"answer.cited[{index}]"))
    cited_ids = [c.get("citation_id") for c in cited if isinstance(c, dict)]
    if len(cited_ids) != len(set(cited_ids)):
        errors.append("answer.cited lists a citation_id more than once")
    closure = claim_citation_closure(claims)
    if set(cited_ids) != closure:
        errors.append(
            f"answer.cited must equal the claims' citation closure: "
            f"missing={sorted(closure - set(cited_ids))} extra={sorted(set(cited_ids) - closure)}"
        )
    return errors


def _answer_status_errors(answer: Dict[str, Any]) -> List[str]:
    status = answer["status"]
    errors: List[str] = []
    if status == "clarifying":
        errors.extend(validate_clarify_request(answer["clarify"]))
        if answer["claims"]:
            errors.append("a clarifying answer carries no claims")
    elif answer["clarify"] is not None:
        errors.append(f"answer.clarify must be null unless status is clarifying (status={status!r})")

    if status in ("answered", "refused"):
        errors.extend(_grounded_answer_errors(answer))
    else:
        errors.extend(_optional_id_errors(answer["bundle_ref"], "answer.bundle_ref"))

    coverage = answer["coverage"]
    if status == "still_processing":
        errors.extend(_still_processing_coverage_errors(coverage))
    elif coverage is not None:
        errors.extend(validate_coverage(coverage))
    return errors


def _grounded_answer_errors(answer: Dict[str, Any]) -> List[str]:
    status, grounding = answer["status"], answer["grounding"]
    errors: List[str] = []
    if not isinstance(answer["bundle_ref"], str) or not answer["bundle_ref"]:
        errors.append(f"a {status} answer must reference its bundle")
    if not isinstance(grounding, dict) or grounding.get("verdict") not in GROUNDING_VERDICTS:
        errors.append(f"a {status} answer must carry a GroundingReport")
    elif status == "answered" and grounding["verdict"] != "render":
        errors.append("an answered status requires grounding verdict 'render'")
    return errors


def _still_processing_coverage_errors(coverage: Any) -> List[str]:
    if coverage is None:
        return ["a still_processing answer must carry coverage naming the unmet documents"]
    errors = validate_coverage(coverage)
    if errors:
        return errors
    if all(r["status"] == "met" for r in coverage["requirements"]):
        return ["a still_processing answer must name at least one unmet requirement"]
    return []


# ---------------------------------------------------------------------------
# Dispatch (§12.4 table)
# ---------------------------------------------------------------------------

# Classes served by the jobs workflow; their inputs are the session itself.
_JOB_CLASSES = frozenset({"note", "session_control"})


def _is_underspecified(sub_ask: Dict[str, Any], accepted: List[str]) -> bool:
    """A retrieval sub-ask is underspecified when nothing scopes the retrieval.

    A time range alone does not scope a retrieval; the downstream workflow
    needs at least one entity hint, domain hint, or resolved scope id. A
    sub-ask whose accepted classes are all jobs needs no scope.
    """
    if accepted and set(accepted) <= _JOB_CLASSES:
        return False
    return not (sub_ask.get("entity_hints") or sub_ask.get("domain_hints") or sub_ask.get("scope_ids"))


def _accepted_classes(sub_ask: Dict[str, Any]) -> List[str]:
    """Return evidence classes whose calibrated score meets SUB_ASK_MIN_CONFIDENCE."""
    return [
        cls for cls, score in sub_ask.get("class_scores", {}).items()
        if (
            cls in EVIDENCE_CLASSES
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and score >= SUB_ASK_MIN_CONFIDENCE
        )
    ]


def _decision(
    dispatch: str, rule: int, reason_codes: List[str], *,
    clarify_kind: Optional[str] = None, workflow_ids: Optional[List[str]] = None,
) -> DispatchDecision:
    return DispatchDecision(
        dispatch=dispatch,  # type: ignore[typeddict-item]
        dispatch_rule=rule,
        clarify_kind=clarify_kind,  # type: ignore[typeddict-item]
        reason_codes=reason_codes,
        workflow_ids=workflow_ids or [],
    )


def dispatch_assist(context: Dict[str, Any], slots: Dict[str, Any]) -> DispatchDecision:
    """Pure dispatch function — first matching rule wins (§12.4 table).

    Args:
        context: the request's AssistRequestContext.
        slots:   a TaskSlots dict (or a mapping with sub_asks and readings_conflict).

    Returns:
        The DispatchDecision for the route span and the executor.

    Raises:
        ContractViolationError: invalid context or slots.
    """
    context_errors = validate_request_context(context)
    if context_errors:
        raise ContractViolationError(f"dispatch_assist rejected the request context: {context_errors}")
    if not isinstance(slots, dict):
        raise ContractViolationError(f"slots={type(slots).__name__}; expected a TaskSlots object")
    sub_asks = slots.get("sub_asks")
    if not isinstance(sub_asks, list):
        raise ContractViolationError(f"slots.sub_asks={sub_asks!r}; expected a list")
    readings_conflict = slots.get("readings_conflict")
    if not isinstance(readings_conflict, bool):
        raise ContractViolationError(f"slots.readings_conflict={readings_conflict!r}; expected bool")
    slot_errors = sub_ask_errors(sub_asks)
    if slot_errors:
        raise ContractViolationError(f"dispatch_assist rejected sub_asks: {slot_errors}")

    decision = _dispatch(context["channel"], sub_asks, readings_conflict)
    logger.info(
        "dispatch request_id=%s trace_id=%s dispatch=%s rule=%d clarify_kind=%s workflows=%d sub_asks=%d",
        context["request_id"], context["trace_id"], decision["dispatch"], decision["dispatch_rule"],
        decision["clarify_kind"], len(decision["workflow_ids"]), len(sub_asks),
    )
    if "needs_plan" in decision["reason_codes"]:
        logger.warning(
            "needs_plan request_id=%s trace_id=%s reasons=%s; planner deferred (SDD §9.2), "
            "expected planning_agent, using clarify(%s)",
            context["request_id"], context["trace_id"], decision["reason_codes"], decision["clarify_kind"],
        )
    return decision


def _dispatch(channel: str, sub_asks: List[Dict[str, Any]], readings_conflict: bool) -> DispatchDecision:
    # Rule 1: ambient transcript is always silent in v1.
    if channel == "ambient_transcript":
        return _decision("silent", 1, ["ambient_v1_silent"])

    accepted_by_ask = [_accepted_classes(sa) for sa in sub_asks]

    # Rule 2: unclear, conflicted, or underspecified -> clarify.
    rule2: List[str] = []
    if not sub_asks:
        rule2.append("no_sub_asks")
    if any(not classes for classes in accepted_by_ask):
        rule2.append("no_accepted_class")
    if any(_is_underspecified(sa, classes) for sa, classes in zip(sub_asks, accepted_by_ask)):
        rule2.append("underspecified")
    if readings_conflict:
        rule2.append("readings_conflict")
    if rule2:
        if readings_conflict:
            kind = "reading"
        elif "no_sub_asks" in rule2 or "no_accepted_class" in rule2:
            kind = "rephrase"
        else:
            kind = "scope"
        return _decision("clarify", 2, rule2, clarify_kind=kind)

    # Rule 3: dependencies or no_workflow -> planning_agent, which maps to
    # clarify while the planner is deferred (SDD §9.2).
    has_depends_on = any(sa["depends_on"] for sa in sub_asks)
    has_no_workflow = any("no_workflow" in classes for classes in accepted_by_ask)
    if has_depends_on or has_no_workflow:
        reasons = ["needs_plan"]
        if has_depends_on:
            reasons.append("depends_on")
        if has_no_workflow:
            reasons.append("no_workflow")
        return _decision("clarify", 3, reasons, clarify_kind="narrow" if has_depends_on else "rephrase")

    # Rules 4–6 count workflows, not sub-asks: a broad sub-ask with two
    # accepted classes fans out to both fixed workflows.
    workflow_ids = [workflow_id_for(cls) for classes in accepted_by_ask for cls in classes]

    if len(workflow_ids) == 1:
        return _decision("workflow", 4, ["single_workflow"], workflow_ids=workflow_ids)
    if len(workflow_ids) <= MAX_FANOUT_WORKFLOWS:
        return _decision("fanout", 5, ["independent_workflows"], workflow_ids=workflow_ids)
    return _decision("clarify", 6, ["fanout_over_cap"], clarify_kind="narrow")
