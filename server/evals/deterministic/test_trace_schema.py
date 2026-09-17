"""
L1 deterministic tests — trace schema and JSONL round-trip.

These tests run on every PR with no model calls (StubAdapter level).
Target: < 10 s total for the deterministic suite.

Passing criteria:
- TraceSpan validation catches missing required keys
- SpanKind and SpanStatus exhaustiveness are stable (new values require a
  version bump, not a silent addition)
- JsonlTraceSink writes a valid span and the file is re-readable
- A stub run produces at least one JSONL line with the correct schema version
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

# Absolute imports work when pytest is run from server/ directory.
from app.agents.trace_contracts import (
    TRACE_SCHEMA_VERSION,
    KIND_REQUIRED_ATTRS,
    SpanKind,
    SpanStatus,
    TraceSpan,
    make_span,
    validate_span,
)
from app.agents.tracing.sinks import JsonlTraceSink
from app.agents.tracing.spans import new_span_id, new_trace_id, utcnow_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_span(**overrides) -> dict:
    """Build a valid route span; used by tests that specifically test route attrs."""
    base = dict(
        trace_id=new_trace_id(),
        span_id=new_span_id(),
        kind="route",
        name="dispatch_assist",
        session_id="sess-test-001",
        started_at=utcnow_iso(),
        duration_ms=12.5,
        status="ok",
        attributes=_attrs_for_kind("route"),
        parent_span_id=None,
    )
    base.update(overrides)
    return make_span(**base)


def _attrs_for_kind(kind: str) -> Dict[str, Any]:
    """Return minimal stub attributes that satisfy KIND_REQUIRED_ATTRS for kind."""
    required = KIND_REQUIRED_ATTRS.get(kind, frozenset())
    stub: Dict[str, Any] = {}
    for key in required:
        # Use type-appropriate stubs so the dict passes isinstance checks downstream.
        if key in {"input_tokens", "output_tokens", "cached_tokens", "repair_retry",
                   "task_count", "expanded_tool_calls", "gates_reattached",
                   "required_count", "remaining_count", "sources_checked_count",
                   "relevant_doc_count", "level", "claims_total", "passed", "refused"}:
            stub[key] = 0
        elif key in {"cost_usd", "temperature", "duration_ms", "latency_ms",
                     "latency_remaining_ms", "wait_ms"}:
            stub[key] = 0.0
        elif key in {"ok", "cache_hit", "stub", "gate_required", "readings_conflict",
                     "schema_valid", "stop"}:
            stub[key] = False
        elif key in {"sub_asks", "violations", "source_refs", "reason_codes"}:
            stub[key] = []
        elif key in {"thresholds", "scope_choice_ids_with_fact_counts",
                     "hits_by_entity", "failed_by_check",
                     "context_tokens_by_segment"}:
            stub[key] = {}
        elif key == "dispatch":
            stub[key] = "silent"
        elif key == "outcome":
            stub[key] = "ready"
        else:
            stub[key] = ""
    return stub


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_trace_schema_version_format():
    parts = TRACE_SCHEMA_VERSION.split(".")
    assert len(parts) == 2, "TRACE_SCHEMA_VERSION must be major.minor"
    assert all(p.isdigit() for p in parts), "TRACE_SCHEMA_VERSION must be numeric"


# ---------------------------------------------------------------------------
# SpanKind exhaustiveness
# ---------------------------------------------------------------------------

EXPECTED_SPAN_KINDS = {
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
}


def test_span_kind_exhaustiveness():
    actual = set(SpanKind.__args__)  # type: ignore[attr-defined]
    assert actual == EXPECTED_SPAN_KINDS, (
        f"SpanKind changed without updating this test.\n"
        f"Added: {actual - EXPECTED_SPAN_KINDS}\n"
        f"Removed: {EXPECTED_SPAN_KINDS - actual}"
    )


EXPECTED_SPAN_STATUSES = {"ok", "error", "refused", "timeout", "cap_hit", "rejected"}


def test_span_status_exhaustiveness():
    actual = set(SpanStatus.__args__)  # type: ignore[attr-defined]
    assert actual == EXPECTED_SPAN_STATUSES


# ---------------------------------------------------------------------------
# validate_span
# ---------------------------------------------------------------------------


def test_validate_span_passes_for_valid_span():
    span = _valid_span()
    errors = validate_span(span)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_validate_span_catches_missing_keys():
    span = _valid_span()
    del span["trace_id"]
    del span["session_id"]
    errors = validate_span(span)
    assert any("trace_id" in e for e in errors)
    assert any("session_id" in e for e in errors)


def test_validate_span_catches_wrong_schema_version():
    span = _valid_span()
    span["trace_schema_version"] = "99.99"
    errors = validate_span(span)
    assert any("trace_schema_version" in e for e in errors)


def test_validate_span_catches_unknown_kind():
    span = _valid_span(kind="nonexistent_kind")
    errors = validate_span(span)
    assert any("kind" in e for e in errors)


def test_validate_span_catches_unknown_status():
    span = _valid_span(status="definitely_not_a_status")
    errors = validate_span(span)
    assert any("status" in e for e in errors)


# ---------------------------------------------------------------------------
# TraceSpan required keys constant
# ---------------------------------------------------------------------------


def test_trace_span_required_keys_match_make_span_output():
    span = _valid_span()
    missing = TraceSpan.REQUIRED_KEYS - span.keys()
    assert missing == frozenset(), f"make_span does not populate: {missing}"


# ---------------------------------------------------------------------------
# JsonlTraceSink round-trip
# ---------------------------------------------------------------------------


def test_jsonl_sink_writes_and_reads_span():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "traces.jsonl"
        sink = JsonlTraceSink(path)

        span = _valid_span()
        sink.emit(span)
        sink.close()

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1, "Expected exactly one JSONL line"

        parsed = json.loads(lines[0])
        assert parsed["trace_schema_version"] == TRACE_SCHEMA_VERSION
        assert parsed["kind"] == "route"
        assert parsed["session_id"] == "sess-test-001"


def test_jsonl_sink_writes_multiple_spans():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "traces.jsonl"
        sink = JsonlTraceSink(path)

        for kind in ("request", "route", "tool_call"):
            sink.emit(_valid_span(kind=kind))
        sink.close()

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        kinds = [json.loads(ln)["kind"] for ln in lines]
        assert kinds == ["request", "route", "tool_call"]


def test_jsonl_sink_appends_across_open_close():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "traces.jsonl"

        sink = JsonlTraceSink(path)
        sink.emit(_valid_span(kind="request"))
        sink.close()

        sink2 = JsonlTraceSink(path)
        sink2.emit(_valid_span(kind="route"))
        sink2.close()

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Stub run: write + validate a full span for each kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(EXPECTED_SPAN_KINDS))
def test_stub_run_every_kind_passes_validation(kind):
    span = make_span(
        trace_id=new_trace_id(),
        span_id=new_span_id(),
        kind=kind,
        name=f"stub_{kind}",
        session_id="sess-test-001",
        started_at=utcnow_iso(),
        duration_ms=1.0,
        status="ok",
        attributes=_attrs_for_kind(kind),
    )
    errors = validate_span(span)
    assert errors == [], f"kind={kind!r} failed validation: {errors}"


def test_validate_span_catches_missing_kind_attrs():
    span = make_span(
        trace_id=new_trace_id(),
        span_id=new_span_id(),
        kind="route",
        name="dispatch_assist",
        session_id="sess-test-001",
        started_at=utcnow_iso(),
        duration_ms=1.0,
        status="ok",
        attributes={},  # empty — missing route required attrs
    )
    errors = validate_span(span)
    assert any("missing required attributes" in e for e in errors)


def test_validate_span_catches_non_mapping_attributes():
    span = make_span(
        trace_id=new_trace_id(),
        span_id=new_span_id(),
        kind="route",
        name="dispatch_assist",
        session_id="sess-test-001",
        started_at=utcnow_iso(),
        duration_ms=1.0,
        status="ok",
        attributes={"dispatch": "silent"},  # valid — satisfies some but not all
    )
    # Deliberately overwrite attributes with a non-dict after construction
    span["attributes"] = "not-a-dict"
    errors = validate_span(span)
    assert any("mapping" in e for e in errors)
