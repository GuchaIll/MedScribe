"""
The registry's two call sites (#51 exit criteria).

One assist-side call site (a fixed workflow running a parallel group) and one
Lane B call site (the safety_and_validate stage), both through
``build_registry``, with receipts and spans checked end to end.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.session.snapshot import SnapshotStore
from app.agents.tool_contracts import validate_tool_result
from app.agents.tools import (
    REAL_TOOL_IDS,
    ToolRequest,
    ToolScope,
    build_registry,
    run_parallel_group,
    stubbed_tool_ids,
)
from app.agents.trace_contracts import validate_span


class RecordingSink:
    def __init__(self):
        self.spans = []

    def emit(self, span):
        self.spans.append(span)


@pytest.fixture
def ctx():
    ctx = MagicMock()
    ctx.db_session_factory = None
    ctx.patient_repo.get_by_id.return_value = SimpleNamespace(
        full_name="Test Patient", dob=None, age=68, sex="F", mrn="MRN-1",
    )
    ctx.record_repo.get_for_patient.return_value = [
        SimpleNamespace(id="rec_88", version=4, is_final=True, structured_data={}),
    ]
    ctx.record_repo.count_for_patient.return_value = 2
    ctx.embedding_service.get_all_patient_facts.return_value = {
        "medication": [{"fact_key": "metformin", "fact_data": {"dose": "1000 mg"}}],
    }
    ctx.clinical_engine.DRUG_CLASS_ALIASES = {"metformin": "biguanide"}
    ctx.clinical_engine.DRUG_EXTRA_CLASSES = {}
    ctx.clinical_engine.MEDICATION_ALLERGY_MAP = {}
    ctx.clinical_engine.generate_suggestions.return_value = {
        "allergy_alerts": [], "drug_interactions": [], "contraindications": [],
        "risk_level": "low",
    }
    return ctx


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def registry(ctx, sink):
    return build_registry(
        ToolScope(session_id="ses_1", patient_id="pat_1"),
        ctx,
        trace_sink=sink,
        snapshot_store=SnapshotStore(),
    )


class TestRegistryComposition:
    def test_every_contract_tool_is_reachable(self, registry):
        assert len(registry.registered()) == 16

    def test_only_the_phase_1a_tools_are_real(self, registry):
        assert set(stubbed_tool_ids(registry)) == set(registry.registered()) - set(REAL_TOOL_IDS)

    def test_stubs_can_be_left_out_entirely(self, ctx):
        registry = build_registry(
            ToolScope(session_id="ses_1", patient_id="pat_1"), ctx, with_stubs=False,
        )
        assert sorted(registry.registered()) == sorted(REAL_TOOL_IDS)


class TestAssistCallSite:
    def test_a_fixed_workflow_runs_a_parallel_group(self, registry, sink):
        """Assist call site: profile (real) beside a retrieval (stub), one group."""
        trace_log = []
        results = run_parallel_group(
            registry,
            [
                ToolRequest("get_patient_profile", {"sections": ["medications"]},
                            caller="fixed_executor", caller_ref="wf_measurement"),
                ToolRequest("retrieve_structured", {"kind": "lab_result", "entity": "rbc"},
                            caller="fixed_executor", caller_ref="wf_measurement",
                            evidence_class="structured"),
            ],
            trace_log=trace_log,
        )

        assert [result["tool_id"] for result in results] == [
            "get_patient_profile", "retrieve_structured",
        ]
        assert all(validate_tool_result(dict(result)) == [] for result in results)
        assert [entry["stub"] for entry in trace_log] == [False, True]
        assert len(sink.spans) == 2
        assert all(validate_span(span) == [] for span in sink.spans)

    def test_the_planner_cannot_widen_its_reach_from_this_registry(self, registry):
        results = run_parallel_group(registry, [
            ToolRequest("check_med_conflicts", {}, caller="planning_agent", caller_ref="plan_1"),
        ])
        assert results[0]["ok"] is False
        assert "not planner-allowlisted" in results[0]["data"]["refusal_reason"]


class TestLaneBCallSite:
    def test_the_safety_stage_runs_all_three_tools(self, registry, sink):
        trace_log = []
        results = run_parallel_group(
            registry,
            [
                ToolRequest("check_med_conflicts",
                            {"medications": [{"name": "metformin", "dose": "1000 mg"}]},
                            caller="lane_b_stage", caller_ref="safety_and_validate"),
                ToolRequest("check_dosage",
                            {"medications": [{"name": "metformin", "dose": "1000 mg"}],
                             "patient_params": {"age": 68}},
                            caller="lane_b_stage", caller_ref="safety_and_validate"),
                ToolRequest("check_metric_alerts", {"labs": []},
                            caller="lane_b_stage", caller_ref="safety_and_validate"),
            ],
            trace_log=trace_log,
        )

        assert [result["tool_id"] for result in results] == [
            "check_med_conflicts", "check_dosage", "check_metric_alerts",
        ]
        assert all(validate_tool_result(dict(result)) == [] for result in results)
        assert all(entry["stub"] is False for entry in trace_log)
        assert all(entry["caller"] == "lane_b_stage" for entry in trace_log)
        assert all(validate_span(span) == [] for span in sink.spans)

    def test_an_enrich_stage_reaches_retrieval(self, registry):
        result = registry.call(
            "retrieve_for_candidates", {"candidate_facts": [{"candidate_id": "cand_3"}]},
            caller="lane_b_stage", caller_ref="enrich",
        )
        assert result["ok"] is True
        assert validate_tool_result(dict(result)) == []
