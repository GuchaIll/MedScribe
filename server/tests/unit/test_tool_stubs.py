"""
Unit tests for the fixture-backed stub tools (#51).

Every contract 1.2 tool id must have a stub whose canned bodies pass contract
validation in all five cases, and every stub call must be marked `stub: true`
so no eval mistakes fixture data for a real backend.
"""

from __future__ import annotations

import json

import pytest

from app.agents.tool_contracts import TOOL_IDS, TOOL_SPECS, validate_tool_result
from app.agents.tools.registry import ToolRegistry, ToolScope
from app.agents.tools.stubs import (
    DEFAULT_CASE,
    FIXTURE_DIR,
    STUB_CASES,
    StubFixtureError,
    load_case,
    register_stub_tools,
)
from app.agents.trace_contracts import validate_span


class RecordingSink:
    def __init__(self):
        self.spans = []

    def emit(self, span):
        self.spans.append(span)


def caller_for(tool_id):
    """A caller the contract allows for this tool."""
    spec = TOOL_SPECS[tool_id]
    if spec["assist_callable"]:
        return "fixed_executor", "wf_test"
    return "lane_b_stage", spec["lane_b_stages"][0]


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def registry(sink):
    return ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"), trace_sink=sink)


class TestFixtureCoverage:
    def test_every_contract_tool_has_a_fixture(self):
        on_disk = {path.stem for path in FIXTURE_DIR.glob("*.json")}
        assert on_disk == set(TOOL_IDS)

    def test_every_fixture_declares_the_ok_case(self):
        for tool_id in TOOL_IDS:
            assert load_case(tool_id, DEFAULT_CASE)["ok"] in (True, False)

    def test_fixtures_only_use_known_cases(self):
        for path in FIXTURE_DIR.glob("*.json"):
            cases = json.loads(path.read_text())["cases"]
            assert set(cases) <= set(STUB_CASES), path.name

    def test_unknown_case_is_rejected(self):
        with pytest.raises(ValueError, match="unknown stub case"):
            load_case("retrieve_docs", "made_up")

    def test_missing_fixture_file_is_reported(self, tmp_path):
        with pytest.raises(StubFixtureError, match="no stub fixture"):
            load_case("retrieve_docs", "ok", fixture_dir=tmp_path)

    def test_malformed_fixture_is_reported(self, tmp_path):
        (tmp_path / "retrieve_docs.json").write_text("{not json")
        with pytest.raises(StubFixtureError, match="not valid JSON"):
            load_case("retrieve_docs", "ok", fixture_dir=tmp_path)

    def test_fixture_without_ok_case_is_reported(self, tmp_path):
        (tmp_path / "retrieve_docs.json").write_text(json.dumps({"cases": {"empty": {}}}))
        with pytest.raises(StubFixtureError, match="must define"):
            load_case("retrieve_docs", "ok", fixture_dir=tmp_path)


class TestStubCalls:
    @pytest.mark.parametrize("case", STUB_CASES)
    def test_every_tool_returns_a_contract_valid_result(self, registry, sink, case):
        stubs = register_stub_tools(registry, case=case)
        for tool_id in TOOL_IDS:
            caller, caller_ref = caller_for(tool_id)
            result = registry.call(tool_id, {}, caller=caller, caller_ref=caller_ref)
            assert validate_tool_result(dict(result)) == [], (tool_id, case)
            assert result["tool_id"] == tool_id
        assert len(stubs.calls) == len(TOOL_IDS)
        assert all(validate_span(span) == [] for span in sink.spans)

    def test_stub_calls_are_flagged_in_receipts_and_spans(self, registry, sink):
        register_stub_tools(registry)
        trace_log = []
        registry.call(
            "retrieve_docs", {"query": "rbc"}, caller="fixed_executor", caller_ref="wf",
            trace_log=trace_log,
        )
        assert trace_log[0]["stub"] is True
        assert sink.spans[0]["attributes"]["stub"] is True

    def test_no_source_case_fails_with_the_contract_error(self, registry):
        stubs = register_stub_tools(registry)
        stubs.set_case("retrieve_source_chunks", "no_source")
        result = registry.call(
            "retrieve_source_chunks", {}, caller="fixed_executor", caller_ref="wf",
        )
        assert result["ok"] is False
        assert result["error"] == "no_source"

    def test_in_flight_case_carries_received_evidence(self, registry):
        stubs = register_stub_tools(registry)
        stubs.set_case("retrieve_docs", "in_flight_doc")
        result = registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        assert result["data"]["in_flight"][0]["pages_total"] == 9
        assert result["citations"][0]["evidence_state"] == "received"

    def test_conflict_case_cites_both_sides(self, registry):
        stubs = register_stub_tools(registry)
        stubs.set_case("retrieve_structured", "chart_vs_session_conflict")
        result = registry.call("retrieve_structured", {}, caller="fixed_executor", caller_ref="wf")
        kinds = {citation["source_kind"] for citation in result["citations"]}
        assert kinds == {"prior_labs", "session_transcript"}
        assert result["data"]["conflict"]["resolution"] == "unresolved"

    def test_a_case_a_tool_does_not_define_falls_back_to_ok(self, registry):
        stubs = register_stub_tools(registry)
        stubs.set_case("generate_note", "chart_vs_session_conflict")
        result = registry.call("generate_note", {}, caller="fixed_executor", caller_ref="wf")
        assert result["ok"] is True
        assert result["data"]["note_id"] == "note_5"

    def test_cases_are_set_per_tool(self, registry):
        stubs = register_stub_tools(registry)
        stubs.set_case("retrieve_docs", "empty")
        empty = registry.call("retrieve_docs", {}, caller="fixed_executor", caller_ref="wf")
        fine = registry.call("retrieve_visits", {}, caller="fixed_executor", caller_ref="wf")
        assert empty["ok"] is False
        assert fine["ok"] is True

    def test_unknown_tool_id_cannot_be_stubbed(self, registry):
        with pytest.raises(ValueError, match="not a contract tool id"):
            register_stub_tools(registry, only=["retrieve_labs"])

    def test_skip_leaves_real_tools_alone(self, registry):
        register_stub_tools(registry, skip=["get_patient_profile"])
        assert "get_patient_profile" not in registry.registered()
