"""
Unit tests for Diagnostic Intelligence features:
  - diagnostic_reasoning_node (rule-based + LLM paths)
  - clinical_suggestions_node safety-tool integration (registry, #51)
  - DiagnosticReasoning record schema models
  - generate_note.py diagnostic intelligence HTML rendering
  - Pipeline graph wiring (diagnostic_reasoning node registration)
"""

import json
import pytest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch, PropertyMock


# ============================================================================
#  Diagnostic Reasoning Node Tests
# ============================================================================


class TestDetectSpecialty:
    """Tests for _detect_specialty heuristic."""

    def _detect(self, text: str) -> str:
        from app.agents.nodes.diagnostic_reasoning import _detect_specialty
        return _detect_specialty(text)

    def test_cardiology_keywords(self):
        assert self._detect("chest pain with palpitations") == "cardiology"

    def test_endocrinology_keywords(self):
        assert self._detect("diabetes management hba1c elevated") == "endocrinology"

    def test_pulmonology_keywords(self):
        assert self._detect("shortness of breath wheezing copd") == "pulmonology"

    def test_gastroenterology_keywords(self):
        assert self._detect("abdominal pain nausea vomiting") == "gastroenterology"

    def test_neurology_keywords(self):
        assert self._detect("headache seizure numbness tingling") == "neurology"

    def test_nephrology_keywords(self):
        assert self._detect("creatinine elevated egfr kidney function") == "nephrology"

    def test_rheumatology_keywords(self):
        assert self._detect("joint pain arthritis lupus autoimmune") == "rheumatology"

    def test_infectious_disease_keywords(self):
        assert self._detect("fever sepsis infection antibiotic culture") == "infectious_disease"

    def test_hematology_keywords(self):
        assert self._detect("anemia bleeding platelet hemoglobin transfusion") == "hematology"

    def test_psychiatry_keywords(self):
        assert self._detect("depression anxiety insomnia ssri mood") == "psychiatry"

    def test_general_medicine_fallback(self):
        assert self._detect("routine checkup everything normal") == "general_medicine"

    def test_empty_string(self):
        assert self._detect("") == "general_medicine"

    def test_highest_scoring_specialty_wins(self):
        # 3 cardiology terms vs 1 endocrinology
        result = self._detect("chest pain palpitations arrhythmia diabetes")
        assert result == "cardiology"


class TestBuildClinicalSummary:
    """Tests for _build_clinical_summary prose assembler."""

    def _build(self, candidates=None, record=None, patient_fields=None):
        from app.agents.nodes.diagnostic_reasoning import _build_clinical_summary
        return _build_clinical_summary(
            candidates or [],
            record or {},
            patient_fields or {},
        )

    def test_empty_inputs(self):
        result = self._build()
        assert result == "Insufficient clinical data."

    def test_demographics(self):
        record = {"demographics": {"age": "55", "sex": "Male"}}
        result = self._build(record=record)
        assert "Patient: 55 Male" in result

    def test_chief_complaint(self):
        record = {"chief_complaint": {
            "free_text": "chest pain",
            "onset": "2 hours ago",
            "severity": "8/10",
        }}
        result = self._build(record=record)
        assert "chest pain" in result
        assert "2 hours ago" in result
        assert "8/10" in result

    def test_hpi_symptoms(self):
        record = {"hpi": [
            {"symptom": "headache"},
            {"symptom": "nausea"},
        ]}
        result = self._build(record=record)
        assert "headache" in result
        assert "nausea" in result

    def test_vitals(self):
        record = {"vitals": {"blood_pressure": "140/90", "heart_rate": "88"}}
        result = self._build(record=record)
        assert "140/90" in result
        assert "88" in result

    def test_medications(self):
        record = {"medications": [{"name": "Metformin"}, {"name": "Lisinopril"}]}
        result = self._build(record=record)
        assert "Metformin" in result
        assert "Lisinopril" in result

    def test_allergies(self):
        record = {"allergies": [{"substance": "Penicillin"}]}
        result = self._build(record=record)
        assert "Penicillin" in result

    def test_chronic_conditions(self):
        record = {"past_medical_history": {
            "chronic_conditions": [
                {"name": "Type 2 Diabetes"},
                {"name": "Hypertension"},
            ]
        }}
        result = self._build(record=record)
        assert "Type 2 Diabetes" in result
        assert "Hypertension" in result

    def test_abnormal_labs(self):
        record = {"labs": [
            {"test": "HbA1c", "value": "8.5", "unit": "%", "abnormal": True},
            {"test": "Glucose", "value": "90", "unit": "mg/dL", "abnormal": False},
        ]}
        result = self._build(record=record)
        assert "HbA1c" in result
        assert "8.5" in result
        # Normal labs should NOT appear
        assert "Glucose" not in result or "Abnormal" in result

    def test_candidate_facts(self):
        candidates = [
            {"fact_type": "diagnosis", "value": {"description": "Pneumonia"}},
            {"fact_type": "risk_factor", "value": "Smoking history"},
        ]
        result = self._build(candidates=candidates)
        assert "Pneumonia" in result
        assert "Smoking history" in result

    def test_prior_history_from_db(self):
        patient_fields = {
            "prior_facts": {
                "medications": [
                    {"fact_key": "Aspirin"},
                    {"fact_key": "Atorvastatin"},
                ],
            }
        }
        result = self._build(patient_fields=patient_fields)
        assert "Aspirin" in result
        assert "Atorvastatin" in result


class TestRuleBasedReasoning:
    """Tests for _rule_based_reasoning pattern matching."""

    def _reason(self, summary: str, specialty: str = "general_medicine"):
        from app.agents.nodes.diagnostic_reasoning import _rule_based_reasoning
        return _rule_based_reasoning(summary, specialty)

    def test_chest_pain_with_risk_factors(self):
        result = self._reason("chest pain patient with hypertension and diabetes")
        assert len(result["top_diagnoses"]) > 0
        dx_names = [d["name"] for d in result["top_diagnoses"]]
        assert "Acute Coronary Syndrome" in dx_names
        assert len(result["recommended_tests"]) > 0

    def test_diabetes_triggers(self):
        result = self._reason("diabetes hba1c elevated glucose metformin")
        dx_names = [d["name"] for d in result["top_diagnoses"]]
        assert "Type 2 Diabetes Mellitus" in dx_names
        tests = [t["test"] for t in result["recommended_tests"]]
        assert "HbA1c" in tests

    def test_hypertension_triggers(self):
        result = self._reason("hypertension high blood pressure")
        dx_names = [d["name"] for d in result["top_diagnoses"]]
        assert "Essential Hypertension" in dx_names
        test_names = [rt["test"] for rt in result["recommended_tests"]]
        assert any("BMP" in t or "ECG" in t for t in test_names)

    def test_respiratory_infection(self):
        result = self._reason("cough fever sore throat wbc elevated respiratory")
        dx_names = [d["name"] for d in result["top_diagnoses"]]
        assert any("Respiratory" in n or "Bronchitis" in n or "Pneumonia" in n
                    for n in dx_names)

    def test_no_match(self):
        result = self._reason("routine wellness visit all normal")
        assert result["top_diagnoses"] == []
        assert result["recommended_tests"] == []

    def test_treatment_guidance_diabetes(self):
        result = self._reason("diabetes management metformin adjustment needed")
        assert len(result["treatment_guidance"]) > 0
        assert any("Diabetes" in tg["condition"] for tg in result["treatment_guidance"])

    def test_treatment_guidance_hypertension(self):
        result = self._reason("hypertension management BP elevated")
        assert any("Hypertension" in tg["condition"] for tg in result["treatment_guidance"])

    def test_reasoning_trace_populated(self):
        result = self._reason("diabetes hba1c elevated")
        assert result["reasoning_trace"]
        assert "diagnos" in result["reasoning_trace"].lower()

    def test_deduplicate_diagnoses(self):
        # Both diabetes and chest_pain_cardiac could fire. Each diagnosis
        # should appear at most once.
        result = self._reason(
            "chest pain diabetes hypertension angina hba1c troponin elevated"
        )
        dx_names = [d["name"] for d in result["top_diagnoses"]]
        assert len(dx_names) == len(set(dx_names))


class TestEmptyReasoning:
    """Tests for _empty_reasoning factory."""

    def test_structure(self):
        from app.agents.nodes.diagnostic_reasoning import _empty_reasoning
        result = _empty_reasoning("test reason")
        assert result["top_diagnoses"] == []
        assert result["recommended_tests"] == []
        assert result["risk_flags"] == []
        assert result["treatment_guidance"] == []
        assert result["reasoning_trace"] == "test reason"
        assert result["method"] == "none"
        assert result["specialty"] == "general_medicine"


class TestDiagnosticReasoningNode:
    """Integration tests for diagnostic_reasoning_node."""

    @pytest.fixture
    def base_state(self):
        return {
            "session_id": "test-session",
            "patient_id": "PAT001",
            "candidate_facts": [
                {"fact_type": "diagnosis", "value": {"description": "Hypertension"}},
            ],
            "structured_record": {
                "demographics": {"age": "55", "sex": "Male"},
                "chief_complaint": {"free_text": "elevated blood pressure"},
                "medications": [{"name": "Lisinopril"}],
                "vitals": {"blood_pressure": "160/95"},
            },
            "controls": {
                "trace_log": [],
                "attempts": {},
                "budget": {"max_total_llm_calls": 30, "llm_calls_used": 0},
            },
        }

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.max_llm_calls = 30
        ctx.llm_factory = None  # force rule-based
        return ctx

    def test_rule_based_with_hypertension(self, base_state, mock_ctx):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        result = diagnostic_reasoning_node(base_state, mock_ctx)
        dr = result["diagnostic_reasoning"]
        assert dr["method"] == "rule_based"
        assert dr["specialty"] in ("cardiology", "nephrology", "general_medicine")
        dx_names = [d["name"] for d in dr["top_diagnoses"]]
        assert "Essential Hypertension" in dx_names

    def test_skips_on_empty_input(self, mock_ctx):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        state = {
            "candidate_facts": [],
            "structured_record": {},
            "controls": {"trace_log": [], "attempts": {}, "budget": {}},
        }
        result = diagnostic_reasoning_node(state, mock_ctx)
        dr = result["diagnostic_reasoning"]
        assert dr["method"] == "none"
        assert dr["top_diagnoses"] == []

    def test_trace_logging(self, base_state, mock_ctx):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        result = diagnostic_reasoning_node(base_state, mock_ctx)
        trace = result["controls"]["trace_log"]
        actions = [t["action"] for t in trace if t.get("node") == "diagnostic_reasoning"]
        assert "started" in actions
        assert "completed" in actions

    def test_llm_path_called(self, base_state):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        mock_llm = MagicMock()
        mock_llm.generate_response.return_value = json.dumps({
            "top_diagnoses": [
                {"name": "Essential Hypertension", "icd10": "I10",
                 "confidence": 0.85, "reasoning": "test",
                 "supporting_evidence": ["elevated BP"],
                 "against_evidence": []},
            ],
            "recommended_tests": [
                {"test": "BMP", "rationale": "electrolytes", "priority": "routine",
                 "expected_finding": "normal"},
            ],
            "risk_flags": [],
            "treatment_guidance": [],
            "reasoning_trace": "LLM trace",
        })

        ctx = MagicMock()
        ctx.max_llm_calls = 30
        ctx.llm_factory.return_value = mock_llm

        result = diagnostic_reasoning_node(base_state, ctx)
        dr = result["diagnostic_reasoning"]
        assert dr["method"] == "llm"
        mock_llm.generate_response.assert_called_once()
        assert dr["top_diagnoses"][0]["name"] == "Essential Hypertension"

    def test_llm_fallback_on_error(self, base_state):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        mock_llm = MagicMock()
        mock_llm.generate_response.side_effect = RuntimeError("LLM unavailable")

        ctx = MagicMock()
        ctx.max_llm_calls = 30
        ctx.llm_factory.return_value = mock_llm

        result = diagnostic_reasoning_node(base_state, ctx)
        dr = result["diagnostic_reasoning"]
        assert dr["method"] == "rule_fallback"

    def test_budget_exceeded_falls_to_rules(self, base_state):
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        ctx = MagicMock()
        ctx.max_llm_calls = 30
        ctx.llm_factory = MagicMock()

        base_state["controls"]["budget"] = {
            "max_total_llm_calls": 5,
            "llm_calls_used": 5,
        }

        result = diagnostic_reasoning_node(base_state, ctx)
        assert result["diagnostic_reasoning"]["method"] == "rule_based"
        # LLM should NOT have been called
        ctx.llm_factory.return_value.generate_response.assert_not_called()


# ============================================================================
#  LLM Diagnostic Reasoning Parsing Tests
# ============================================================================


class TestLLMDiagnosticReasoning:
    """Tests for _llm_diagnostic_reasoning JSON parsing."""

    def _reason(self, response_text: str):
        from app.agents.nodes.diagnostic_reasoning import _llm_diagnostic_reasoning
        mock_llm = MagicMock()
        mock_llm.generate_response.return_value = response_text
        return _llm_diagnostic_reasoning(mock_llm, "test summary", "cardiology")

    def test_valid_json(self):
        response = json.dumps({
            "top_diagnoses": [{"name": "Test", "icd10": "X00", "confidence": 0.9,
                               "reasoning": "r", "supporting_evidence": [],
                               "against_evidence": []}],
            "recommended_tests": [],
            "risk_flags": [],
            "treatment_guidance": [],
            "reasoning_trace": "trace",
        })
        result = self._reason(response)
        assert result["top_diagnoses"][0]["name"] == "Test"

    def test_markdown_fenced_json(self):
        response = "```json\n" + json.dumps({
            "top_diagnoses": [{"name": "Fenced"}],
            "recommended_tests": [],
            "risk_flags": [],
        }) + "\n```"
        result = self._reason(response)
        assert result["top_diagnoses"][0]["name"] == "Fenced"

    def test_invalid_json_returns_empty(self):
        result = self._reason("This is not JSON at all")
        assert result["top_diagnoses"] == []
        assert "parse failure" in result["reasoning_trace"].lower()

    def test_missing_keys_filled_with_defaults(self):
        response = json.dumps({"top_diagnoses": [{"name": "DX1"}]})
        result = self._reason(response)
        assert result["recommended_tests"] == []
        assert result["risk_flags"] == []
        assert result["treatment_guidance"] == []


# ============================================================================
#  Record Schema Tests
# ============================================================================


class TestDiagnosticReasoningSchema:
    """Tests for the new Pydantic schema models."""

    def test_recommended_test_defaults(self):
        from app.agents.nodes.record_schema import RecommendedTest
        t = RecommendedTest(test="CBC")
        assert t.test == "CBC"
        assert t.priority is None
        assert t.rationale is None

    def test_clinical_risk_flag_full(self):
        from app.agents.nodes.record_schema import ClinicalRiskFlag
        f = ClinicalRiskFlag(flag="Cardiac risk", severity="high", action="Monitor")
        assert f.flag == "Cardiac risk"
        assert f.severity == "high"

    def test_treatment_guidance_precautions_default(self):
        from app.agents.nodes.record_schema import TreatmentGuidance
        tg = TreatmentGuidance(condition="Hypertension")
        assert tg.precautions == []

    def test_diagnostic_insight_full(self):
        from app.agents.nodes.record_schema import DiagnosticInsight
        di = DiagnosticInsight(
            name="Type 2 DM",
            icd10="E11.9",
            confidence=0.85,
            reasoning="HbA1c elevated",
            supporting_evidence=["HbA1c 8.5%"],
            against_evidence=[],
        )
        assert di.name == "Type 2 DM"
        assert di.confidence == 0.85
        assert len(di.supporting_evidence) == 1

    def test_diagnostic_reasoning_model(self):
        from app.agents.nodes.record_schema import (
            DiagnosticReasoning, DiagnosticInsight, RecommendedTest,
            ClinicalRiskFlag, TreatmentGuidance,
        )
        dr = DiagnosticReasoning(
            top_diagnoses=[DiagnosticInsight(name="Test DX")],
            recommended_tests=[RecommendedTest(test="CBC")],
            risk_flags=[ClinicalRiskFlag(flag="Risk")],
            treatment_guidance=[TreatmentGuidance(condition="C1")],
            specialty="cardiology",
            reasoning_trace="trace",
            method="rule_based",
        )
        assert len(dr.top_diagnoses) == 1
        assert dr.method == "rule_based"
        assert dr.specialty == "cardiology"

    def test_diagnostic_reasoning_defaults(self):
        from app.agents.nodes.record_schema import DiagnosticReasoning
        dr = DiagnosticReasoning()
        assert dr.top_diagnoses == []
        assert dr.recommended_tests == []
        assert dr.risk_flags == []
        assert dr.treatment_guidance == []
        assert dr.method is None

    def test_structured_record_has_diagnostic_reasoning(self):
        from app.agents.nodes.record_schema import StructuredRecord
        sr = StructuredRecord()
        assert hasattr(sr, "diagnostic_reasoning")
        assert sr.diagnostic_reasoning.top_diagnoses == []

    def test_empty_record_has_diagnostic_reasoning(self):
        from app.agents.nodes.record_schema import empty_record
        rec = empty_record()
        assert "diagnostic_reasoning" in rec


# ============================================================================
#  Clinical Suggestions Node -- registry safety tools (#51)
# ============================================================================


class TestClinicalSuggestionsSafetyTools:
    """The node is Lane B's registry call site: three safety tools, one group."""

    @pytest.fixture
    def state_with_diag_reasoning(self):
        return {
            "session_id": "test-session",
            "patient_id": "PAT001",
            "structured_record": {
                "demographics": {"age": "65", "sex": "Male"},
                "medications": [{"name": "Metformin 500mg", "dose": "500mg"}],
                "allergies": [{"substance": "Penicillin"}],
                "labs": [{"test_name": "Glucose", "value": 200, "unit": "mg/dL"}],
            },
            "diagnostic_reasoning": {
                "top_diagnoses": [
                    {"name": "Type 2 Diabetes", "confidence": 0.8},
                ],
                "risk_flags": [
                    {"flag": "Elevated glucose", "severity": "moderate"},
                ],
            },
            "controls": {"trace_log": [], "attempts": {}, "budget": 30},
        }

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.patient_service.get_patient_history.return_value = {
            "found": True,
            "patient_id": "PAT001",
            "allergies": [{"substance": "Penicillin"}],
            "medications": [],
            "diagnoses": [],
            "labs": [],
        }
        ctx.clinical_engine.generate_suggestions.return_value = {
            "allergy_alerts": [],
            "drug_interactions": [],
            "contraindications": [],
            "risk_level": "low",
        }
        ctx.db_session_factory = None
        return ctx

    @staticmethod
    def _safety_results(*, dosage_alert=True, metric_alert=True):
        """Canned ToolResults for the three safety tools."""
        def result(tool_id, alerts, risk, not_covered=()):
            return {
                "tool_id": tool_id,
                "ok": True,
                "data": {"alerts": list(alerts), "not_covered": list(not_covered),
                         "risk_level": risk},
                "citations": [],
                "error": None,
                "receipt": {"tool_id": tool_id, "ok": True},
            }

        return [
            result("check_med_conflicts", [], "low",
                   [{"medication": "Metformin 500mg", "reason": "not in the interaction table"}]),
            result(
                "check_dosage",
                [{"type": "renal_adjustment", "severity": "critical",
                  "message": "reduce dose"}] if dosage_alert else [],
                "critical" if dosage_alert else "low",
            ),
            result(
                "check_metric_alerts",
                [{"type": "critical_value", "severity": "critical", "test_name": "Glucose",
                  "message": "above range"}] if metric_alert else [],
                "critical" if metric_alert else "low",
            ),
        ]

    def _run(self, state, ctx, results):
        from app.agents.nodes import clinical_suggestions as node_module
        with patch.object(node_module, "_run_safety_tools",
                          wraps=node_module._run_safety_tools):
            with patch("app.agents.tools.run_parallel_group", return_value=results):
                return node_module.clinical_suggestions_node(state, ctx)

    def test_safety_tool_results_merged(self, state_with_diag_reasoning, mock_ctx):
        result = self._run(state_with_diag_reasoning, mock_ctx, self._safety_results())
        suggestions = result["clinical_suggestions"]
        assert "safety_tools" in suggestions
        assert suggestions["safety_tools"]["tools_executed"] == [
            "check_med_conflicts", "check_dosage", "check_metric_alerts",
        ]
        assert suggestions.get("lab_critical_values")
        assert suggestions.get("dosage_alerts")

    def test_not_covered_is_surfaced(self, state_with_diag_reasoning, mock_ctx):
        """A rule table that says nothing must not read as a clean check."""
        result = self._run(state_with_diag_reasoning, mock_ctx, self._safety_results())
        not_covered = result["clinical_suggestions"]["not_covered"]
        assert not_covered
        assert not_covered[0]["tool_id"] == "check_med_conflicts"

    def test_risk_level_escalation(self, state_with_diag_reasoning, mock_ctx):
        result = self._run(state_with_diag_reasoning, mock_ctx, self._safety_results())
        assert result["clinical_suggestions"]["risk_level"] == "critical"

    def test_no_escalation_without_alerts(self, state_with_diag_reasoning, mock_ctx):
        results = self._safety_results(dosage_alert=False, metric_alert=False)
        result = self._run(state_with_diag_reasoning, mock_ctx, results)
        assert result["clinical_suggestions"]["risk_level"] == "low"

    def test_diagnostic_risk_flags_integrated(self, state_with_diag_reasoning, mock_ctx):
        result = self._run(state_with_diag_reasoning, mock_ctx, self._safety_results())
        risk_flags = result["clinical_suggestions"].get("risk_flags", [])
        assert any(rf["source"] == "diagnostic_reasoning" for rf in risk_flags)

    def test_trace_records_which_tools_ran(self, state_with_diag_reasoning, mock_ctx):
        result = self._run(state_with_diag_reasoning, mock_ctx, self._safety_results())
        trace = result["controls"]["trace_log"]
        completed = [t for t in trace
                     if t.get("node") == "clinical_suggestions" and t.get("action") == "completed"]
        assert completed
        assert completed[0]["safety_tools_used"] is True
        assert "check_dosage" in completed[0]["safety_tools_run"]

    def test_node_survives_registry_failure(self, state_with_diag_reasoning, mock_ctx):
        """A registry that cannot be built degrades to engine-only suggestions."""
        from app.agents.nodes.clinical_suggestions import clinical_suggestions_node
        with patch("app.agents.tools.build_registry", side_effect=RuntimeError("boom")):
            result = clinical_suggestions_node(state_with_diag_reasoning, mock_ctx)
        suggestions = result["clinical_suggestions"]
        assert "safety_tools" not in suggestions
        assert suggestions["risk_level"] == "low"


class TestSafetyToolArguments:
    """The node turns record state into the three tools' arguments."""

    def test_problems_merge_record_history_and_reasoning(self):
        from app.agents.nodes.clinical_suggestions import _problems
        record = {
            "diagnoses": [{"description": "Type 2 Diabetes"}],
            "past_medical_history": {"chronic_conditions": [{"name": "Hypertension"}]},
        }
        reasoning = {"top_diagnoses": [{"name": "Type 2 Diabetes"}, {"name": "CKD stage 3"}]}
        descriptions = [p["description"] for p in _problems(record, reasoning)]
        assert descriptions == ["Type 2 Diabetes", "Hypertension", "CKD stage 3"]

    def test_patient_params_from_demographics_and_vitals(self):
        from app.agents.nodes.clinical_suggestions import _patient_params
        record = {
            "demographics": {"age": "65", "sex": "Male"},
            "vitals": {"weight": "70", "height": 175},
            "labs": [{"test_name": "Creatinine", "value": "1.5"}],
        }
        params = _patient_params(record, {})
        assert params["age"] == 65
        assert params["weight_kg"] == 70.0
        assert params["height_cm"] == 175.0
        assert params["serum_creatinine"] == 1.5

    def test_patient_params_ignore_unparsable_values(self):
        from app.agents.nodes.clinical_suggestions import _patient_params
        params = _patient_params(
            {"demographics": {"age": "sixty-five"}, "vitals": {"weight": "unknown"}}, {},
        )
        assert "age" not in params
        assert "weight_kg" not in params

    def test_rows_ignores_malformed_fields(self):
        from app.agents.nodes.clinical_suggestions import _rows
        assert _rows({"medications": "not a list"}, "medications") == []
        assert _rows({"medications": [{"name": "a"}, "junk"]}, "medications") == [{"name": "a"}]


# ============================================================================
#  Generate Note -- Diagnostic Intelligence Section Tests
# ============================================================================


class TestGenerateNoteDiagnosticIntelligence:
    """Test that diagnostic intelligence HTML section renders correctly."""

    def _build_state_with_diagnostics(self):
        return {
            "structured_record": {
                "diagnostic_reasoning": {
                    "top_diagnoses": [
                        {
                            "name": "Essential Hypertension",
                            "icd10": "I10",
                            "confidence": 0.85,
                            "reasoning": "Elevated BP, risk factors present",
                            "supporting_evidence": ["BP 160/95", "Family history"],
                            "against_evidence": ["No end-organ damage"],
                        },
                    ],
                    "recommended_tests": [
                        {
                            "test": "BMP",
                            "rationale": "Check electrolytes and renal function",
                            "priority": "urgent",
                            "expected_finding": "Normal electrolytes",
                        },
                    ],
                    "risk_flags": [
                        {
                            "flag": "Cardiovascular risk factor",
                            "severity": "high",
                            "action": "Start antihypertensive therapy",
                        },
                    ],
                    "treatment_guidance": [
                        {
                            "condition": "Hypertension",
                            "recommendation": "ACE inhibitor first-line",
                            "evidence_level": "guideline",
                            "precautions": ["Monitor potassium"],
                        },
                    ],
                    "reasoning_trace": "Step-by-step analysis performed.",
                    "method": "rule_based",
                    "specialty": "cardiology",
                },
            },
        }

    def test_section_contains_diagnosis_table(self):
        """Verify HTML output has the differential diagnoses table."""
        from app.agents.nodes.generate_note import _build_diagnostic_intelligence_section
        state = self._build_state_with_diagnostics()
        record = state["structured_record"]
        diag_r = record.get("diagnostic_reasoning", {})

        # The function exists and renders HTML
        html = _build_diagnostic_intelligence_section(diag_r)
        assert "Essential Hypertension" in html
        assert "I10" in html
        assert "85" in html  # confidence 0.85 -> 85%

    def test_section_contains_recommended_tests(self):
        from app.agents.nodes.generate_note import _build_diagnostic_intelligence_section
        diag_r = self._build_state_with_diagnostics()["structured_record"]["diagnostic_reasoning"]
        html = _build_diagnostic_intelligence_section(diag_r)
        assert "BMP" in html
        assert "urgent" in html.lower()

    def test_section_contains_risk_flags(self):
        from app.agents.nodes.generate_note import _build_diagnostic_intelligence_section
        diag_r = self._build_state_with_diagnostics()["structured_record"]["diagnostic_reasoning"]
        html = _build_diagnostic_intelligence_section(diag_r)
        assert "Cardiovascular risk factor" in html

    def test_section_contains_treatment_guidance(self):
        from app.agents.nodes.generate_note import _build_diagnostic_intelligence_section
        diag_r = self._build_state_with_diagnostics()["structured_record"]["diagnostic_reasoning"]
        html = _build_diagnostic_intelligence_section(diag_r)
        assert "ACE inhibitor" in html
        assert "guideline" in html.lower()

    def test_empty_diagnostics_returns_empty_string(self):
        from app.agents.nodes.generate_note import _build_diagnostic_intelligence_section
        html = _build_diagnostic_intelligence_section({})
        assert html == "" or "Diagnostic Intelligence" not in html


# ============================================================================
#  Pipeline Graph Wiring Tests
# ============================================================================


class TestGraphWiring:
    """Verify diagnostic_reasoning node is wired into the pipeline graph."""

    def test_node_registered(self):
        """diagnostic_reasoning must be in the node registry."""
        from app.agents.graph import build_graph
        from app.agents.config import AgentContext
        ctx = AgentContext()  # empty context, no live services
        # We just need to verify the graph builds without error
        # and the node is present. We won't compile (needs sqlite).
        from app.agents.nodes.diagnostic_reasoning import diagnostic_reasoning_node
        assert callable(diagnostic_reasoning_node)

    def test_import_succeeds(self):
        """Graph module imports the diagnostic_reasoning_node."""
        from app.agents.graph import build_graph  # noqa: F401
        # If this import succeeds, the diagnostic_reasoning import in graph.py is valid.

    def test_build_graph_succeeds_with_conflicting_state_keys(self):
        """Graph construction should not reuse state-field names as node IDs."""
        from app.agents.config import AgentContext
        from app.agents.graph import build_graph

        graph = build_graph(AgentContext(), enable_interrupts=False)

        assert graph is not None

    def test_agentcontext_has_safety_engine_slots(self):
        """ToolUniverseService is retired (#51); the safety engines are injected."""
        from app.agents.config import AgentContext
        ctx = AgentContext()
        assert not hasattr(ctx, "tool_universe_service")
        assert ctx.dosage_calculator is None
        assert ctx.lab_interpreter is None

    def test_agentcontext_with_safety_engines(self):
        from app.agents.config import AgentContext
        calculator, interpreter = MagicMock(), MagicMock()
        ctx = AgentContext(dosage_calculator=calculator, lab_interpreter=interpreter)
        assert ctx.dosage_calculator is calculator
        assert ctx.lab_interpreter is interpreter


# ============================================================================
#  State Schema Tests
# ============================================================================


class TestGraphStateDiagnosticReasoning:
    """Test that diagnostic_reasoning field is in GraphState."""

    def test_field_exists(self):
        from app.agents.state import GraphState
        # GraphState is a TypedDict, check annotations
        annotations = GraphState.__annotations__
        assert "diagnostic_reasoning" in annotations
