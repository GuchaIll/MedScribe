"""
Unit tests for the three safety tools (#51).

Each wraps an existing engine unchanged and reports what the rule tables do not
cover. Silence from a table is never reported as a clean check.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.tool_contracts import NOT_COVERED_ERROR, validate_tool_result
from app.agents.tools.errors import ToolPermissionError
from app.agents.tools.registry import ToolCall, ToolRegistry, ToolScope
from app.agents.tools.safety import (
    make_dosage_handler,
    make_med_conflicts_handler,
    make_metric_alerts_handler,
    register_safety_tools,
)


def call(tool_id, args):
    return ToolCall(
        tool_id=tool_id,
        args=args,
        scope=ToolScope(session_id="ses_1", patient_id="pat_1"),
        caller="lane_b_stage",
        caller_ref="safety_and_validate",
        invocation_id="inv_1",
    )


@pytest.fixture
def engine():
    engine = MagicMock()
    engine.DRUG_CLASS_ALIASES = {"warfarin": "anticoagulant", "metformin": "biguanide"}
    engine.DRUG_EXTRA_CLASSES = {}
    engine.MEDICATION_ALLERGY_MAP = {"amoxicillin": ["penicillin"]}
    engine.generate_suggestions.return_value = {
        "allergy_alerts": [
            {"severity": "critical", "message": "penicillin cross-reactivity",
             "substance": "amoxicillin"},
        ],
        "drug_interactions": [],
        "contraindications": [],
        "risk_level": "critical",
    }
    return engine


class TestMedConflicts:
    def test_alerts_are_normalized(self, engine):
        outcome = make_med_conflicts_handler(engine=engine)(
            call("check_med_conflicts", {"medications": [{"name": "amoxicillin"}],
                                         "allergies": [{"substance": "penicillin"}]}),
        )
        assert outcome.ok is True
        assert outcome.data["alerts"][0]["type"] == "allergy"
        assert outcome.data["alerts"][0]["severity"] == "critical"
        assert outcome.data["risk_level"] == "critical"

    def test_untabled_medication_is_reported_not_dropped(self, engine):
        outcome = make_med_conflicts_handler(engine=engine)(
            call("check_med_conflicts", {"medications": [
                {"name": "warfarin"}, {"name": "obeticholic acid"},
            ]}),
        )
        assert outcome.ok is True
        assert outcome.data["not_covered"] == [
            {"medication": "obeticholic acid", "reason": "not in the interaction table"},
        ]

    def test_nothing_covered_returns_the_contract_error(self, engine):
        outcome = make_med_conflicts_handler(engine=engine)(
            call("check_med_conflicts", {"medications": [{"name": "obeticholic acid"}]}),
        )
        assert outcome.ok is False
        assert outcome.error == NOT_COVERED_ERROR
        assert outcome.data["risk_level"] == "unknown"

    def test_no_medications_is_a_clean_empty_result(self, engine):
        outcome = make_med_conflicts_handler(engine=engine)(
            call("check_med_conflicts", {"medications": []}),
        )
        assert outcome.ok is True
        assert outcome.data["alerts"] == []

    def test_missing_engine_reports_everything_uncovered(self):
        handler = make_med_conflicts_handler(engine=None)
        outcome = handler(call("check_med_conflicts", {"medications": [{"name": "warfarin"}]}))
        assert outcome.error == NOT_COVERED_ERROR
        assert outcome.data["not_covered"][0]["reason"] in (
            "engine unavailable", "not in the interaction table",
        )

    def test_malformed_medications_are_rejected(self, engine):
        with pytest.raises(ValueError, match="medications"):
            make_med_conflicts_handler(engine=engine)(
                call("check_med_conflicts", {"medications": "warfarin"}),
            )


class TestDosage:
    @pytest.fixture
    def calculator(self):
        calculator = MagicMock()
        calculator.check_dosage_appropriateness.return_value = {
            "appropriate": False,
            "issues": [{"type": "renal_adjustment", "severity": "critical",
                        "message": "reduce dose", "recommendation": "500 mg BID"}],
        }
        return calculator

    def test_issues_become_alerts(self, calculator):
        outcome = make_dosage_handler(calculator=calculator)(
            call("check_dosage", {"medications": [{"name": "metformin", "dose": "1000 mg"}],
                                  "patient_params": {"age": 75, "serum_creatinine": 1.5}}),
        )
        assert outcome.ok is True
        assert outcome.data["alerts"][0]["medication"] == "metformin"
        assert outcome.data["risk_level"] == "critical"

    def test_missing_patient_params_is_not_covered(self, calculator):
        outcome = make_dosage_handler(calculator=calculator)(
            call("check_dosage", {"medications": [{"name": "metformin", "dose": "1000 mg"}],
                                  "patient_params": {}}),
        )
        assert outcome.ok is False
        assert outcome.error == NOT_COVERED_ERROR
        assert "no age, weight, or renal parameters" in outcome.data["not_covered"][0]["reason"]

    def test_medication_without_a_dose_is_not_covered(self, calculator):
        outcome = make_dosage_handler(calculator=calculator)(
            call("check_dosage", {"medications": [{"name": "metformin"}],
                                  "patient_params": {"age": 75}}),
        )
        assert outcome.error == NOT_COVERED_ERROR
        assert outcome.data["not_covered"][0]["reason"] == "no dose recorded"

    def test_calculator_failure_is_reported_per_medication(self, calculator):
        calculator.check_dosage_appropriateness.side_effect = RuntimeError("table missing")
        outcome = make_dosage_handler(calculator=calculator)(
            call("check_dosage", {"medications": [{"name": "metformin", "dose": "1000 mg"}],
                                  "patient_params": {"age": 75}}),
        )
        assert outcome.error == NOT_COVERED_ERROR
        assert outcome.data["not_covered"][0]["reason"] == "dosage check failed"

    def test_rejects_malformed_patient_params(self, calculator):
        with pytest.raises(ValueError, match="patient_params"):
            make_dosage_handler(calculator=calculator)(
                call("check_dosage", {"medications": [{"name": "metformin", "dose": "1 g"}],
                                      "patient_params": "75 years"}),
            )


class TestMetricAlerts:
    @pytest.fixture
    def interpreter(self):
        interpreter = MagicMock()
        interpreter.interpret.return_value = {
            "interpretations": [
                {"test_name": "potassium", "value": 6.4, "unit": "mmol/L",
                 "reference_range": "3.5-5.1", "severity": "critical",
                 "interpretation": "critically high"},
                {"test_name": "anti-mullerian hormone", "value": 1.1,
                 "reference_range": None, "severity": "info",
                 "interpretation": "no reference range available"},
            ],
            "risk_flags": [],
            "summary": "",
        }
        return interpreter

    def test_reads_the_engines_interpretations_key(self, interpreter):
        """The retired tool_universe service read 'results' and saw nothing."""
        outcome = make_metric_alerts_handler(interpreter=interpreter)(
            call("check_metric_alerts", {"labs": [{"test_name": "potassium", "value": 6.4}]}),
        )
        assert outcome.ok is True
        assert outcome.data["alerts"][0]["test_name"] == "potassium"
        assert outcome.data["risk_level"] == "critical"

    def test_analyte_without_a_range_is_not_covered(self, interpreter):
        outcome = make_metric_alerts_handler(interpreter=interpreter)(
            call("check_metric_alerts", {"labs": [{"test_name": "potassium", "value": 6.4}]}),
        )
        assert outcome.data["not_covered"][0]["test_name"] == "anti-mullerian hormone"

    def test_no_covered_analyte_returns_not_covered(self, interpreter):
        interpreter.interpret.return_value = {
            "interpretations": [
                {"test_name": "x", "reference_range": None, "severity": "info"},
            ],
            "risk_flags": [], "summary": "",
        }
        outcome = make_metric_alerts_handler(interpreter=interpreter)(
            call("check_metric_alerts", {"labs": [{"test_name": "x", "value": 1}]}),
        )
        assert outcome.ok is False
        assert outcome.error == NOT_COVERED_ERROR

    def test_borderline_values_are_not_alerts(self, interpreter):
        interpreter.interpret.return_value = {
            "interpretations": [
                {"test_name": "sodium", "reference_range": "135-145", "severity": "borderline"},
            ],
            "risk_flags": [], "summary": "",
        }
        outcome = make_metric_alerts_handler(interpreter=interpreter)(
            call("check_metric_alerts", {"labs": [{"test_name": "sodium", "value": 134}]}),
        )
        assert outcome.ok is True
        assert outcome.data["alerts"] == []
        assert outcome.data["risk_level"] == "low"

    def test_metrics_the_engine_skipped_are_reported(self, interpreter):
        interpreter.interpret.return_value = {
            "interpretations": [
                {"test_name": "potassium", "reference_range": "3.5-5.1", "severity": "high"},
            ],
            "risk_flags": [], "summary": "",
        }
        outcome = make_metric_alerts_handler(interpreter=interpreter)(
            call("check_metric_alerts", {"labs": [
                {"test_name": "potassium", "value": 5.9}, {"value": 3},
            ]}),
        )
        assert any("had no test name or value" in item["reason"]
                   for item in outcome.data["not_covered"])


class TestThroughTheRegistry:
    def test_lane_b_may_call_all_three(self, engine):
        registry = ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"))
        register_safety_tools(registry, None, engine=engine,
                              calculator=MagicMock(), interpreter=MagicMock())
        result = registry.call(
            "check_med_conflicts",
            {"medications": [{"name": "amoxicillin"}], "allergies": [{"substance": "penicillin"}]},
            caller="lane_b_stage", caller_ref="safety_and_validate",
        )
        assert validate_tool_result(dict(result)) == []
        assert result["ok"] is True

    def test_planner_may_not_reach_them_directly(self, engine):
        registry = ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"))
        register_safety_tools(registry, None, engine=engine,
                              calculator=MagicMock(), interpreter=MagicMock())
        with pytest.raises(ToolPermissionError):
            registry.call("check_metric_alerts", {}, caller="planning_agent", caller_ref="plan_1")

    def test_safety_tools_are_not_stubs(self, engine):
        registry = ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"))
        register_safety_tools(registry, None, engine=engine,
                              calculator=MagicMock(), interpreter=MagicMock())
        assert registry.is_stub("check_dosage") is False
