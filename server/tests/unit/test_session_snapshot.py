"""
Unit tests for the session patient snapshot and get_patient_profile (#51).

Plan §6: load once per session, reuse on the next compile, invalidate on the
§6.2 triggers. The exit criterion is a cache hit on the second compile.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.nodes.load_patient_context import load_patient_context_node
from app.agents.session.snapshot import (
    INVALIDATION_REASONS,
    SnapshotStore,
    empty_snapshot,
    load_snapshot,
    snapshot_sections,
)
from app.agents.tool_contracts import NO_SOURCE_ERROR, validate_tool_result
from app.agents.tools.profile import register_profile_tool
from app.agents.tools.registry import ToolRegistry, ToolScope


@pytest.fixture
def store():
    return SnapshotStore()


@pytest.fixture
def ctx():
    ctx = MagicMock()
    ctx.patient_repo.get_by_id.return_value = SimpleNamespace(
        full_name="Test Patient", dob=date(1958, 4, 2), age=68, sex="F", mrn="MRN-1",
    )
    ctx.record_repo.get_for_patient.return_value = [
        SimpleNamespace(
            id="rec_88", version=4, is_final=True,
            structured_data={"chief_complaint": "follow-up", "visit_date": "2026-06-02"},
        ),
    ]
    ctx.record_repo.count_for_patient.return_value = 3
    ctx.embedding_service.get_all_patient_facts.return_value = {
        "allergy": [{"fact_key": "penicillin", "fact_data": {"severity": "severe"}}],
        "medication": [{"fact_key": "metformin", "fact_data": {"dose": "1000 mg"}}],
        "lab_result": [{"fact_key": "rbc", "fact_data": {"value": 3.9}}],
    }
    return ctx


class TestLoading:
    def test_loads_every_section_from_the_repositories(self, ctx, store):
        snapshot = load_snapshot("ses_1", "pat_1", ctx, store=store)
        assert snapshot["source"] == "db"
        assert snapshot["version"] == 4
        assert snapshot["visit_count"] == 3
        assert snapshot["demographics"]["mrn"] == "MRN-1"
        assert set(snapshot["facts_by_type"]) == {"allergy", "medication", "lab_result"}
        assert snapshot["retrieval_keys"]["latest_record_id"] == "rec_88"

    def test_second_load_is_a_cache_hit(self, ctx, store):
        """Exit criterion: the second compile in a session does not reload."""
        load_snapshot("ses_1", "pat_1", ctx, store=store)
        second = load_snapshot("ses_1", "pat_1", ctx, store=store)
        assert second["source"] == "cache"
        assert ctx.patient_repo.get_by_id.call_count == 1

    def test_force_reload_bypasses_the_cache(self, ctx, store):
        load_snapshot("ses_1", "pat_1", ctx, store=store)
        reloaded = load_snapshot("ses_1", "pat_1", ctx, force_reload=True, store=store)
        assert reloaded["source"] == "db"
        assert ctx.patient_repo.get_by_id.call_count == 2

    def test_another_session_does_not_share_the_cache(self, ctx, store):
        load_snapshot("ses_1", "pat_1", ctx, store=store)
        other = load_snapshot("ses_2", "pat_1", ctx, store=store)
        assert other["source"] == "db"

    def test_no_context_returns_an_empty_snapshot(self, store):
        snapshot = load_snapshot("ses_1", "pat_1", None, store=store)
        assert snapshot["loaded_from_db"] is False
        assert snapshot["source"] == "empty"

    def test_a_failing_repository_degrades_that_section_only(self, ctx, store):
        ctx.embedding_service.get_all_patient_facts.side_effect = RuntimeError("db down")
        snapshot = load_snapshot("ses_1", "pat_1", ctx, store=store)
        assert snapshot["facts_by_type"] == {}
        assert snapshot["demographics"]["mrn"] == "MRN-1"
        assert snapshot["loaded_from_db"] is True

    def test_blank_identifiers_are_rejected(self, ctx, store):
        with pytest.raises(ValueError, match="session_id"):
            load_snapshot("", "pat_1", ctx, store=store)
        with pytest.raises(ValueError, match="patient_id"):
            load_snapshot("ses_1", "", ctx, store=store)


class TestInvalidation:
    def test_invalidating_forces_the_next_load_to_hit_the_db(self, ctx, store):
        load_snapshot("ses_1", "pat_1", ctx, store=store)
        assert store.invalidate("ses_1", "pat_1", "clinician_edit") is True
        assert load_snapshot("ses_1", "pat_1", ctx, store=store)["source"] == "db"

    def test_unknown_reason_is_rejected(self, store):
        with pytest.raises(ValueError, match="unknown invalidation reason"):
            store.invalidate("ses_1", "pat_1", "felt_like_it")

    def test_the_plan_triggers_are_all_accepted(self, store):
        for reason in INVALIDATION_REASONS:
            assert store.invalidate("ses_1", "pat_1", reason) is False

    def test_a_patient_switch_never_serves_the_previous_patient(self, ctx, store):
        store.put("ses_1", empty_snapshot("pat_other"))
        snapshot = load_snapshot("ses_1", "pat_1", ctx, store=store)
        assert snapshot["patient_id"] == "pat_1"
        assert snapshot["source"] == "db"


class TestSectionViews:
    def test_sections_are_views_over_one_fact_copy(self, ctx, store):
        snapshot = load_snapshot("ses_1", "pat_1", ctx, store=store)
        sections = snapshot_sections(snapshot)
        assert sections["allergies"][0]["fact_key"] == "penicillin"
        assert sections["medications"][0]["fact_key"] == "metformin"
        assert sections["recent_labs_summary"][0]["fact_key"] == "rbc"

    def test_a_section_falls_back_to_the_finalized_record(self):
        snapshot = empty_snapshot("pat_1")
        snapshot["prior_record"] = {"problems": [{"description": "type 2 diabetes"}]}
        assert snapshot_sections(snapshot, ["problems"])["problems"][0]["description"] == (
            "type 2 diabetes"
        )

    def test_unknown_section_is_rejected(self):
        with pytest.raises(ValueError, match="unknown snapshot section"):
            snapshot_sections(empty_snapshot("pat_1"), ["vitals"])


class TestGetPatientProfileTool:
    @pytest.fixture
    def registry(self, ctx, store):
        registry = ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"))
        register_profile_tool(registry, ctx, store=store, replace=False)
        return registry

    def test_returns_sections_and_a_snapshot_citation(self, registry):
        result = registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")
        assert validate_tool_result(dict(result)) == []
        assert result["data"]["snapshot_version"] == 4
        assert result["citations"][0]["source_id"] == "rec_88#v4"
        assert result["citations"][0]["evidence_state"] == "authorized"

    def test_second_call_reports_a_cache_hit(self, registry):
        registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")
        second = registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")
        assert second["data"]["cache_hit"] is True
        assert second["receipt"]["cache_hit"] is True

    def test_requested_sections_are_honoured(self, registry):
        result = registry.call(
            "get_patient_profile", {"sections": ["allergies"]},
            caller="fixed_executor", caller_ref="wf",
        )
        assert list(result["data"]["sections"]) == ["allergies"]

    def test_unknown_section_fails_the_call_without_raising(self, registry):
        result = registry.call(
            "get_patient_profile", {"sections": ["vitals"]},
            caller="fixed_executor", caller_ref="wf",
        )
        assert result["ok"] is False

    def test_empty_patient_state_returns_no_source(self, store):
        registry = ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_new"))
        register_profile_tool(registry, None, store=store, replace=False)
        result = registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")
        assert result["ok"] is False
        assert result["error"] == NO_SOURCE_ERROR

    def test_missing_patient_scope_is_refused(self, ctx, store):
        registry = ToolRegistry(ToolScope(session_id="ses_1"))
        register_profile_tool(registry, ctx, store=store, replace=False)
        from app.agents.tools.errors import ToolScopeError

        with pytest.raises(ToolScopeError):
            registry.call("get_patient_profile", {}, caller="fixed_executor", caller_ref="wf")


class TestLaneBNode:
    def _state(self):
        return {
            "session_id": "ses_1",
            "patient_id": "pat_1",
            "controls": {"attempts": {}, "budget": {}, "trace_log": []},
        }

    def test_node_fills_patient_record_fields_from_the_snapshot(self, ctx, store):
        result = load_patient_context_node(self._state(), ctx, store=store)
        fields = result["patient_record_fields"]
        assert fields["demographics"]["mrn"] == "MRN-1"
        assert set(fields["prior_facts"]) == {"allergy", "medication", "lab_result"}
        assert fields["visit_count"] == 3
        assert fields["snapshot_version"] == 4
        assert fields["snapshot_source"] == "db"

    def test_second_compile_in_a_session_hits_the_cache(self, ctx, store):
        load_patient_context_node(self._state(), ctx, store=store)
        second = load_patient_context_node(self._state(), ctx, store=store)
        assert second["patient_record_fields"]["snapshot_source"] == "cache"
        assert ctx.record_repo.get_for_patient.call_count == 1

    def test_missing_patient_id_skips_the_load(self, ctx, store):
        state = self._state()
        state["patient_id"] = ""
        result = load_patient_context_node(state, ctx, store=store)
        assert result["patient_record_fields"]["loaded_from_db"] is False
        assert ctx.patient_repo.get_by_id.call_count == 0

    def test_new_patient_skips_the_load(self, ctx, store):
        state = self._state()
        state["is_new_patient"] = True
        result = load_patient_context_node(state, ctx, store=store)
        assert result["patient_record_fields"]["prior_facts"] == {}
        assert ctx.patient_repo.get_by_id.call_count == 0

    def test_snapshot_failure_degrades_to_empty_context(self, ctx, monkeypatch, store):
        def boom(*args, **kwargs):
            raise RuntimeError("redis and db down")

        monkeypatch.setattr("app.agents.nodes.load_patient_context.load_snapshot", boom)
        result = load_patient_context_node(self._state(), ctx, store=store)
        assert result["patient_record_fields"]["loaded_from_db"] is False
        trace = result["controls"]["trace_log"]
        assert any(entry.get("action") == "error" for entry in trace)
