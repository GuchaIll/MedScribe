"""
Unit tests for the shared tool registry (agent refactor Phase 1A, #51).

Covers the traps the exit criteria name — scope keys in model args, a caller
reaching for a tool it may not use — plus the receipt, span, and failure
behaviour every call site depends on.
"""

from __future__ import annotations

import pytest

from app.agents.tool_contracts import RUNTIME_CONTRACT_VERSION, validate_tool_result
from app.agents.tools.errors import (
    ToolArgumentError,
    ToolPermissionError,
    ToolResultContractError,
    ToolScopeError,
    UnknownToolError,
)
from app.agents.tools.registry import (
    HANDLER_ERROR,
    TOOL_INVOCATION_EVENT,
    ToolOutcome,
    ToolRegistry,
    ToolScope,
    hash_args,
)
from app.agents.trace_contracts import validate_span


class RecordingSink:
    def __init__(self):
        self.spans = []

    def emit(self, span):
        self.spans.append(span)


def ok_outcome(call):
    return ToolOutcome(
        ok=True,
        data={"hits": 1, "scope_seen": call.scope.as_dict(), "arg_keys": sorted(call.args)},
        citations=[{
            "source_kind": "prior_docs",
            "source_id": "chunk:doc_1:p1:c1",
            "snippet": "text",
            "observed_at": None,
            "received_at": "2026-09-16T09:00:00Z",
            "evidence_state": "materialized",
            "locator": {"page": 1, "char_start": 0, "char_end": 4},
            "score": 0.5,
        }],
    )


@pytest.fixture
def scope():
    return ToolScope(session_id="ses_1", patient_id="pat_1", tenant_id="ten_1")


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def registry(scope, sink):
    return ToolRegistry(scope, trace_sink=sink)


class TestScope:
    def test_session_id_is_required(self):
        with pytest.raises(ValueError, match="session_id"):
            ToolScope(session_id="")

    def test_as_dict_omits_unset_identifiers(self):
        assert ToolScope(session_id="ses_1").as_dict() == {"session_id": "ses_1"}

    def test_missing_reports_absent_keys(self, scope):
        assert scope.missing(["patient_id", "doctor_id"]) == ["doctor_id"]


class TestRegistration:
    def test_rejects_non_contract_tool_id(self, registry):
        with pytest.raises(UnknownToolError):
            registry.register("retrieve_labs", ok_outcome)

    def test_rejects_duplicate_without_replace(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ValueError, match="already registered"):
            registry.register("retrieve_docs", ok_outcome)

    def test_replace_swaps_a_stub_for_a_real_backend(self, registry):
        registry.register("retrieve_docs", ok_outcome, stub=True)
        registry.register("retrieve_docs", ok_outcome, version="real-1", stub=False, replace=True)
        assert registry.is_stub("retrieve_docs") is False
        assert registry.registered()["retrieve_docs"].version == "real-1"

    def test_rejects_non_callable_handler(self, registry):
        with pytest.raises(TypeError):
            registry.register("retrieve_docs", "not callable")

    def test_rejects_unknown_scope_requirement(self, registry):
        with pytest.raises(ValueError, match="not a scope key"):
            registry.register("retrieve_docs", ok_outcome, requires_scope=["mrn"])


class TestPermissions:
    def test_planner_cannot_call_a_safety_tool(self, registry):
        """Exit criterion: disallowed-tool trap is rejected."""
        registry.register("check_dosage", ok_outcome)
        with pytest.raises(ToolPermissionError, match="planner-allowlisted"):
            registry.call("check_dosage", {}, caller="planning_agent", caller_ref="plan_1")

    def test_lane_b_stage_must_be_allowed_for_the_tool(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ToolPermissionError, match="finalize"):
            registry.call("retrieve_docs", {}, caller="lane_b_stage", caller_ref="finalize")

    def test_lane_b_allowed_stage_passes(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        result = registry.call("retrieve_docs", {}, caller="lane_b_stage", caller_ref="enrich")
        assert result["ok"] is True

    def test_assist_cannot_call_a_compile_only_tool(self, registry):
        registry.register("retrieve_for_candidates", ok_outcome)
        with pytest.raises(ToolPermissionError, match="assist path"):
            registry.call("retrieve_for_candidates", {}, caller="fixed_executor", caller_ref="wf")

    def test_unknown_caller_is_refused(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ToolPermissionError, match="unknown caller"):
            registry.call("retrieve_docs", {}, caller="somebody", caller_ref="x")

    def test_unregistered_tool_raises(self, registry):
        with pytest.raises(UnknownToolError):
            registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")


class TestArgumentValidation:
    def test_model_supplied_scope_key_is_rejected(self, registry):
        """Exit criterion: scope-key trap is rejected."""
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ToolArgumentError, match="scope keys"):
            registry.call(
                "retrieve_docs", {"query": "rbc", "patient_id": "other"},
                caller="planning_agent", caller_ref="plan_1", model_supplied=True,
            )

    def test_nested_scope_key_is_found(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ToolArgumentError) as excinfo:
            registry.call(
                "retrieve_docs", {"filters": [{"tenant_id": "t2"}]},
                caller="fixed_executor", caller_ref="wf", model_supplied=True,
            )
        assert "filters[0].tenant_id" in excinfo.value.violations[0]

    def test_runtime_args_are_checked_too(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ToolArgumentError):
            registry.call(
                "retrieve_docs", {"session_id": "ses_2"},
                caller="fixed_executor", caller_ref="wf",
            )

    def test_scope_is_injected_not_passed_in_args(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        result = registry.call(
            "retrieve_docs", {"query": "rbc"}, caller="fixed_executor", caller_ref="wf",
        )
        assert result["data"]["arg_keys"] == ["query"]
        assert result["data"]["scope_seen"] == {
            "session_id": "ses_1", "patient_id": "pat_1", "tenant_id": "ten_1",
        }

    def test_missing_required_scope_is_refused(self, sink):
        registry = ToolRegistry(ToolScope(session_id="ses_1"), trace_sink=sink)
        registry.register("get_patient_profile", ok_outcome, requires_scope=["patient_id"])
        with pytest.raises(ToolScopeError, match="patient_id"):
            registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")


class TestReceiptsAndSpans:
    def test_receipt_lands_in_the_trace_log(self, registry):
        trace_log = []
        registry.register("retrieve_docs", ok_outcome, version="stub-1", stub=True)
        result = registry.call(
            "retrieve_docs", {"query": "rbc"}, caller="fixed_executor", caller_ref="wf",
            trace_log=trace_log, evidence_class="document",
        )
        entry = trace_log[0]
        assert entry["event"] == TOOL_INVOCATION_EVENT
        assert entry["stub"] is True
        assert entry["evidence_class"] == "document"
        assert entry["tool_id"] == "retrieve_docs"
        assert entry["invocation_id"] == result["receipt"]["invocation_id"]

    def test_receipt_matches_the_contract(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        result = registry.call(
            "retrieve_docs", {"query": "rbc"}, caller="fixed_executor", caller_ref="wf",
        )
        receipt = result["receipt"]
        assert receipt["contract_version"] == RUNTIME_CONTRACT_VERSION
        assert receipt["session_id"] == "ses_1"
        assert receipt["source_refs"] == ["chunk:doc_1:p1:c1"]
        assert validate_tool_result(dict(result)) == []

    def test_receipt_carries_no_argument_values(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        result = registry.call(
            "retrieve_docs", {"query": "secret patient phrase"},
            caller="fixed_executor", caller_ref="wf",
        )
        assert "secret" not in str(result["receipt"])
        assert result["receipt"]["args_hash"] == hash_args({"query": "secret patient phrase"})

    def test_span_is_emitted_and_valid(self, registry, sink):
        registry.register("retrieve_docs", ok_outcome, stub=True)
        registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        span = sink.spans[0]
        assert validate_span(span) == []
        assert span["kind"] == "tool_call"
        assert span["name"] == "tool.retrieve_docs"
        assert span["attributes"]["stub"] is True
        assert span["status"] == "ok"

    def test_metrics_are_incremented(self, scope):
        class Metrics:
            def __init__(self):
                self.calls = []
                self.tool_call_total = self
                self.tool_latency_ms = self
                self.tool_error_total = self

            def labels(self, **kwargs):
                self.calls.append(kwargs)
                return self

            def inc(self):
                pass

            def observe(self, value):
                pass

        metrics = Metrics()
        registry = ToolRegistry(scope, metrics=metrics)
        registry.register("retrieve_docs", ok_outcome)
        registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        assert {"tool_id": "retrieve_docs", "stub": "false", "ok": "true"} in metrics.calls

    def test_a_failing_sink_does_not_fail_the_call(self, scope):
        class BadSink:
            def emit(self, span):
                raise RuntimeError("sink down")

        registry = ToolRegistry(scope, trace_sink=BadSink())
        registry.register("retrieve_docs", ok_outcome)
        assert registry.call(
            "retrieve_docs", {}, caller="fixed_executor", caller_ref="wf",
        )["ok"] is True


class TestFailurePaths:
    def test_handler_exception_becomes_a_failed_result(self, registry, sink):
        def boom(call):
            raise RuntimeError("backend down")

        registry.register("retrieve_docs", boom)
        result = registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        assert result["ok"] is False
        assert result["error"] == HANDLER_ERROR
        assert result["receipt"]["ok"] is False
        assert sink.spans[0]["status"] == "error"

    def test_result_that_breaks_the_contract_is_refused(self, registry):
        """A retrieval tool cannot report success with no citations."""
        registry.register("retrieve_docs", lambda call: ToolOutcome(ok=True, data={}))
        with pytest.raises(ToolResultContractError, match="ungrounded"):
            registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")

    def test_handler_returning_the_wrong_type_is_refused(self, registry):
        registry.register("retrieve_docs", lambda call: {"ok": True})
        with pytest.raises(ToolResultContractError, match="ToolOutcome"):
            registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")

    def test_no_source_failure_is_contract_valid(self, registry):
        registry.register(
            "retrieve_docs",
            lambda call: ToolOutcome(ok=False, data={"reason": "nothing"}, error="no_source"),
        )
        result = registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        assert validate_tool_result(dict(result)) == []
        assert result["error"] == "no_source"

    def test_blank_caller_ref_is_rejected(self, registry):
        registry.register("retrieve_docs", ok_outcome)
        with pytest.raises(ValueError, match="caller_ref"):
            registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="")


class TestDatabaseSessions:
    def test_session_is_opened_and_closed_for_tools_that_need_one(self, scope):
        opened, closed = [], []

        class Session:
            def close(self):
                closed.append(self)

        def factory():
            session = Session()
            opened.append(session)
            return session

        seen = {}

        def handler(call):
            seen["db"] = call.db
            return ok_outcome(call)

        registry = ToolRegistry(scope, db_session_factory=factory)
        registry.register("retrieve_docs", handler, needs_db=True)
        registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        assert seen["db"] is opened[0]
        assert closed == opened

    def test_no_session_is_opened_for_tools_that_do_not_need_one(self, scope):
        def factory():
            raise AssertionError("must not be called")

        registry = ToolRegistry(scope, db_session_factory=factory)
        registry.register("retrieve_docs", ok_outcome)
        assert registry.call(
            "retrieve_docs", {}, caller="fixed_executor", caller_ref="wf",
        )["ok"] is True
