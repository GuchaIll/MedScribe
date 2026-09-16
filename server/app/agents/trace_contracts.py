"""
Trace contract types for the agent runtime.

All spans are OpenTelemetry-shaped so exporting to a tracing backend later
is an adapter, not a schema change.  PHI rules: production spans carry ids,
hashes, counts, and codes only — never utterance text, prompts, completions,
or tool payloads.  Payload capture is allowed only when
TRACE_CAPTURE_PAYLOADS=true (dev / eval runs on synthetic data).

Schema version is versioned independently from the runtime contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

TRACE_SCHEMA_VERSION = "0.1"

# ---------------------------------------------------------------------------
# Span kinds
# ---------------------------------------------------------------------------

SpanKind = Literal[
    "request",
    "addressee",
    "route",
    "slot_extract",
    "plan",
    "plan_validate",
    "workflow",
    "cascade_level",
    "tool_call",
    "synthesis",
    "grounding_check",
    "judge",
    "render",
    "handoff",
    "materialization_wait",
]

SpanStatus = Literal["ok", "error", "refused", "timeout", "cap_hit", "rejected"]

# ---------------------------------------------------------------------------
# Core span
# ---------------------------------------------------------------------------


class TraceSpan(dict):
    """
    OpenTelemetry-shaped span dict.  Typed as a plain dict subclass so it
    serialises directly to JSON without a custom encoder.

    Required keys are enforced by validate_span(); optional keys depend on
    the span kind (see kind-specific attribute tables in §19.2).
    """

    REQUIRED_KEYS = frozenset(
        {
            "trace_schema_version",
            "trace_id",
            "span_id",
            "parent_span_id",
            "kind",
            "name",
            "session_id",
            "started_at",
            "duration_ms",
            "status",
            "attributes",
        }
    )


def make_span(
    *,
    trace_id: str,
    span_id: str,
    kind: SpanKind,
    name: str,
    session_id: str,
    started_at: str,
    duration_ms: float,
    status: SpanStatus,
    attributes: Dict[str, Any],
    parent_span_id: Optional[str] = None,
) -> TraceSpan:
    """Construct a fully-populated TraceSpan dict."""
    span: TraceSpan = TraceSpan(
        {
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "kind": kind,
            "name": name,
            "session_id": session_id,
            "started_at": started_at,
            "duration_ms": duration_ms,
            "status": status,
            "attributes": attributes,
        }
    )
    return span


def validate_span(span: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors; empty means valid."""
    errors: List[str] = []
    missing = TraceSpan.REQUIRED_KEYS - span.keys()
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
    if "trace_schema_version" in span and span["trace_schema_version"] != TRACE_SCHEMA_VERSION:
        errors.append(
            f"trace_schema_version mismatch: "
            f"got {span['trace_schema_version']!r}, expected {TRACE_SCHEMA_VERSION!r}"
        )
    if "kind" in span and span["kind"] not in _VALID_KINDS:
        errors.append(f"unknown kind: {span['kind']!r}")
    if "status" in span and span["status"] not in _VALID_STATUSES:
        errors.append(f"unknown status: {span['status']!r}")
    return errors


_VALID_KINDS = set(SpanKind.__args__)  # type: ignore[attr-defined]
_VALID_STATUSES = set(SpanStatus.__args__)  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Kind-specific required attribute sets (used by L1 validators)
# ---------------------------------------------------------------------------

LLM_SPAN_KINDS: frozenset[SpanKind] = frozenset(
    {"addressee", "slot_extract", "plan", "render", "synthesis", "judge"}
)

LLM_REQUIRED_ATTRS = frozenset(
    {
        "prompt_id",
        "prompt_version",
        "prompt_sha",
        "model_role",
        "provider",
        "model",
        "temperature",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "cost_usd",
        "context_tokens_by_segment",
        "schema_valid",
        "repair_retry",
        "finish_reason",
    }
)

ROUTE_REQUIRED_ATTRS = frozenset(
    {
        "as_of_receipt",
        "sub_asks",
        "readings_conflict",
        "thresholds",
        "dispatch",
        "dispatch_rule",
        "clarify_kind",
        "scope_library_version",
        "reason_codes",
    }
)

PLAN_VALIDATE_REQUIRED_ATTRS = frozenset(
    {
        "task_count",
        "expanded_tool_calls",
        "violations",
        "gates_reattached",
    }
)

HANDOFF_REQUIRED_ATTRS = frozenset(
    {
        "workflow_id",
        "reason",
        "required_count",
        "remaining_count",
        "sources_checked_count",
        "latency_remaining_ms",
        "violations",
    }
)

MATERIALIZATION_WAIT_REQUIRED_ATTRS = frozenset(
    {
        "relevant_doc_count",
        "wait_ms",
        "outcome",
        "physician_choice",
    }
)

TOOL_CALL_REQUIRED_ATTRS = frozenset(
    {
        "invocation_id",
        "tool_id",
        "tool_version",
        "caller",
        "args_hash",
        "ok",
        "cache_hit",
        "latency_ms",
        "stub",
        "gate_required",
        "evidence_class",
    }
)

CASCADE_LEVEL_REQUIRED_ATTRS = frozenset(
    {
        "level",
        "stop",
        "stop_rule",
        "hits_by_entity",
    }
)

GROUNDING_CHECK_REQUIRED_ATTRS = frozenset(
    {
        "claims_total",
        "passed",
        "failed_by_check",
        "refused",
    }
)

# ---------------------------------------------------------------------------
# Feedback events
# ---------------------------------------------------------------------------

FeedbackKind = Literal[
    "answer_accept",
    "answer_wrong",
    "missing_source",
    "clarify_answered",
    "scope_selected",
    "still_processing_choice",
    "chip_accept",
    "chip_dismiss",
]


class FeedbackEvent(dict):
    """
    feedback.submitted event.  Joined to traces offline; this is the
    human-in-the-loop signal from §18.6 rule 9.

    PHI rules apply: reason_code is a code, not free text.
    """

    REQUIRED_KEYS = frozenset({"trace_id", "kind", "reason_code"})


def make_feedback_event(
    *,
    trace_id: str,
    kind: FeedbackKind,
    reason_code: str,
) -> FeedbackEvent:
    return FeedbackEvent(
        {
            "trace_id": trace_id,
            "kind": kind,
            "reason_code": reason_code,
        }
    )


def validate_feedback_event(event: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    missing = FeedbackEvent.REQUIRED_KEYS - event.keys()
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
    if "kind" in event and event["kind"] not in _VALID_FEEDBACK_KINDS:
        errors.append(f"unknown feedback kind: {event['kind']!r}")
    return errors


_VALID_FEEDBACK_KINDS = set(FeedbackKind.__args__)  # type: ignore[attr-defined]
