"""
Locks the copilot runtime contract (agent refactor Phase 1A, contract 1.2):
two-stage intent gate with sub-asks, dispatch table, request/evidence/control/
output carriers, shared tool registry, Lane B outputs, and the golden sets.

If one of these fails, the contract changed. Follow change control in
docs/copilot_runtime_contract.md §10 instead of editing the expectation.
"""

import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from app.agents.compile_contracts import (
    DELTA_ACTION,
    FACT_STATUSES,
    PUSH_ALERT_SEVERITIES,
    REVIEW_STATES,
    SAFETY_SEVERITIES,
    SAFETY_ALERT_TYPES,
    CandidateFact,
    CompileJob,
    FactIdentity,
    FactProvenance,
    LaneBOutputs,
    SafetyAlertCard,
    duplicate_active_keys,
    fact_source_ids,
    make_fact_key,
    renders_alert_card,
    supersede,
)
from app.agents import config as agent_config
from app.agents.config import (
    MAX_FANOUT_WORKFLOWS,
    POST_BARRIER_RESERVE_MS,
    RECHECK_INTERVAL_MS,
    REFERENCE_RESOLUTION_WAIT_MS,
    SUB_ASK_MIN_CONFIDENCE,
)
from app.agents.intent import executor_contract
from app.agents.intent.executor_contract import (
    ANSWER_STATUSES,
    CLARIFY_KINDS,
    DISPATCH_VALUES,
    OUTCOME_KINDS,
    OUTCOME_PAYLOAD,
    PHYSICIAN_CHOICES,
    AssistAnswer,
    AssistRequestContext,
    ClarifyRequest,
    DispatchDecision,
    EvidenceRef,
    PlanRequest,
    ReceiptWatermarks,
    ScopeChoice,
    WorkflowOutcome,
    dispatch_assist,
    grounding_verdict,
    make_evidence_ref,
    validate_assist_answer,
    validate_request_context,
    validate_workflow_outcome,
    workflow_id_for,
)
from app.agents.intent.policy import AMBIENT_CHIP_MIN_CONFIDENCE, resolve_intervention
from app.agents.intent.schemas import (
    ADDRESSEES,
    ASSIST_TASKS,
    CHANNELS,
    ENCOUNTER_STATUSES,
    EVIDENCE_CLASSES,
    EXPLICIT_CHANNELS,
    FORBIDDEN_DECISION_KEYS,
    GATE_INPUT_SPEAKERS,
    INTERVENTION_MODES,
    JOB_TASKS,
    LANES,
    TASK_LANE,
    TASK_SUBTYPES,
    AddresseeDecision,
    IntentDecision,
    SubAsk,
    TaskSlots,
    validate_intent_decision,
)
from app.agents.tool_contracts import (
    EVIDENCE_STATES,
    FAILURE_CODES,
    INGEST_LEVELS,
    LOCATOR_KIND_BY_SOURCE,
    REQUIREMENT_STATUSES,
    LANE_B_STAGES,
    NO_SOURCE_ERROR,
    NOT_COVERED_ERROR,
    PLANNER_ALLOWLIST,
    RUNTIME_CONTRACT_VERSION,
    SCOPE_ARG_KEYS,
    SOURCE_KINDS,
    TOOL_CALLERS,
    TOOL_IDS,
    TOOL_SPECS,
    TOOL_WRITES,
    BundleClosedError,
    Citation,
    Claim,
    ContractViolationError,
    CoverageBanner,
    Derivation,
    DocumentSpan,
    EvidenceBundle,
    RequirementOutcome,
    RowRef,
    ToolInvocationReceipt,
    TranscriptSpan,
    append_result,
    close_bundle,
    empty_coverage,
    make_citation_id,
    new_bundle,
    validate_model_tool_args,
    validate_tool_result,
)

_SERVER_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _SERVER_ROOT / "tests" / "fixtures"
_CONTRACT_DOC = _SERVER_ROOT.parent / "docs" / "copilot_runtime_contract.md"

_TASK_OPTIONS = [*TASK_SUBTYPES, None]


def _load(name):
    with (_FIXTURES / name).open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _addressees_for(channel):
    return ["copilot"] if channel in EXPLICIT_CHANNELS else list(ADDRESSEES)


def _addressee(**overrides):
    addressee = {
        "addressee": "copilot",
        "confidence": 1.0,
        "channel": "explicit_ui",
        "reason_codes": ["explicit_channel"],
    }
    addressee.update(overrides)
    return addressee


def _slots(**overrides):
    slots = {
        "task_subtype": "factoid",
        "query_rewrite": "most recent RBC",
        "time_range": None,
        "domain_hints": ["hematology"],
        "source_prefs": ["observation"],
        "entity_hints": ["rbc"],
        "speak_policy": "text_only",
        "sub_asks": [],
        "readings_conflict": False,
    }
    slots.update(overrides)
    return slots


def _sub_ask(**overrides):
    sa = {
        "sub_ask_id": "sa-1",
        "span": "most recent RBC",
        "class_scores": {"measurement": 0.92},
        "entity_hints": ["rbc"],
        "domain_hints": ["hematology"],
        "scope_ids": [],
        "time_range": None,
        "depends_on": [],
    }
    sa.update(overrides)
    return sa


def _decision(addressee=None, task="default", **overrides):
    decision = {
        "addressee": addressee or _addressee(),
        "task": _slots() if task == "default" else task,
        "intervene": True,
        "urgency": "interactive",
    }
    decision.update(overrides)
    return decision


def _citation(source_kind="observation", source_id="obs-123", **overrides):
    locators = {
        "observation": {"kind": "row_ref", "table": "observations", "row_id": source_id, "column": "value"},
        "visit": {"kind": "row_ref", "table": "visits", "row_id": source_id, "column": None},
        "document": {
            "kind": "document_span", "doc_id": source_id, "chunk_id": "chunk-1",
            "page": 1, "char_start": 0, "char_end": 40,
        },
        "session_transcript": {"kind": "transcript_span", "segment_id": source_id, "t_start": 1.0, "t_end": 2.5},
    }
    citation = {
        "citation_id": None,
        "source_kind": source_kind,
        "source_id": source_id,
        "snippet": None,
        "observed_at": "2026-08-01",
        "received_at": "2026-08-01T08:00:00Z",
        "evidence_state": "materialized",
        "locator": locators.get(source_kind),
        "score": None,
    }
    citation.update(overrides)
    if "citation_id" not in overrides:
        try:
            citation["citation_id"] = make_citation_id(source_kind, source_id, citation["locator"])
        except ContractViolationError:
            # invalid kinds and locators are what some cases test; the validator
            # reports those and skips the id check
            citation["citation_id"] = f"{source_kind}:{source_id}"
    return citation


# Citation ids of the default observation citations (SDD A.2 RowRef locator key).
OBS_123 = "observation:obs-123#observations/obs-123/value"
OBS_9 = "observation:obs-9#observations/obs-9/value"


def _fact(fact_key, fact_id, status="active"):
    return {
        "fact_key": fact_key,
        "fact_id": fact_id,
        "status": status,
        "superseded_by": None,
        "confidence": 0.9,
        "type": "allergy",
        "value": fact_key.split(":")[-1],
        "provenance": {
            "evidence": [_citation("session_transcript", f"seg-{fact_id}")],
            "extractor": "compile_candidates",
            "prompt_version": "extract/v1",
        },
    }


def _watermarks(**overrides):
    watermarks = {
        "as_of_receipt": "2026-09-30T12:00:00+00:00",
        "snapshot_generation": 3,
        "transcript_stream_id": "1727697600000-0",
        "draft_version": "d-7",
    }
    watermarks.update(overrides)
    return watermarks


def _context(**overrides):
    context = {
        "request_id": "req-1",
        "session_id": "session-1",
        "trace_id": "trace-1",
        "channel": "explicit_ui",
        "watermarks": _watermarks(),
        "deadline_at": "2026-09-30T12:00:08+00:00",
        "resumes_answer_id": None,
        "patient_id": "patient-1",
        "clinician_id": "clinician-1",
    }
    context.update(overrides)
    return context


def _tool_result(**overrides):
    result = {
        "tool_id": "retrieve_structured",
        "ok": True,
        "data": {"analyte": "rbc", "value": 4.6, "unit": "10^6/uL"},
        "citations": [_citation()],
        "error": None,
        "receipt": {
            "contract_version": RUNTIME_CONTRACT_VERSION,
            "invocation_id": "invoke-1",
            "session_id": "session-1",
            "tool_id": "retrieve_structured",
            "tool_version": "v1",
            "caller": "fixed_executor",
            "caller_ref": "intent-1",
            "args_hash": "a" * 64,
            "ok": True,
            "error": None,
            "cache_hit": False,
            "latency_ms": 12.5,
            "source_refs": ["obs-123"],
            "created_at": "2026-08-01T08:00:00Z",
        },
    }
    result.update(overrides)
    return result


def _receipted(result, invocation_id, args_hash):
    receipt = {**result["receipt"], "invocation_id": invocation_id, "args_hash": args_hash}
    return {**result, "receipt": receipt}


def _claim(claim_id="c-1", citation_ids=(OBS_123,), derivation=None):
    return {
        "claim_id": claim_id,
        "text": "RBC was 4.6",
        "claim_type": "lab_value",
        "value": 4.6,
        "unit": "10^6/uL",
        "date": "2026-08-01",
        "negated": False,
        "citation_ids": list(citation_ids),
        "derivation": derivation,
        "evidence_state": "materialized",
    }


def _requirement(doc_id="doc-1", status="met", failure_code=None, need="indexed"):
    return {"doc_id": doc_id, "need": need, "status": status, "failure_code": failure_code}


def _answer(**overrides):
    answer = {
        "answer_id": "ans-1",
        "request_id": "req-1",
        "session_id": "session-1",
        "status": "answered",
        "claims": [_claim()],
        "cited": [_citation()],
        "bundle_ref": "bundle-1",
        "grounding": {"claims_checked": 1, "unsupported_claim_ids": [], "verdict": "render"},
        "clarify": None,
        "coverage": None,
        "watermarks": _watermarks(),
        "resumes_answer_id": None,
        "created_at": "2026-09-30T12:00:03+00:00",
    }
    answer.update(overrides)
    return answer


@pytest.mark.unit
class TestGateSchema:
    def test_contract_version(self):
        assert RUNTIME_CONTRACT_VERSION == "1.2"

    def test_enums_are_frozen(self):
        assert ADDRESSEES == ("patient", "copilot", "unknown")
        assert CHANNELS == ("explicit_ui", "wake_word", "ambient_transcript")
        assert TASK_SUBTYPES == (
            "factoid",
            "trajectory",
            "compare",
            "safety",
            "compile",
            "note",
            "doc_ingest",
            "session_control",
            "unknown",
        )

    def test_evidence_classes_are_frozen(self):
        assert EVIDENCE_CLASSES == (
            "session",
            "measurement",
            "document",
            "trajectory",
            "compare",
            "safety",
            "general",
            "note",
            "session_control",
            "no_workflow",
        )

    def test_job_and_intake_classes_are_not_evidence_classes(self):
        assert "compile" not in EVIDENCE_CLASSES
        assert "doc_ingest" not in EVIDENCE_CLASSES

    def test_decision_shapes_are_frozen(self):
        assert set(IntentDecision.__annotations__) == {"addressee", "task", "intervene", "urgency"}
        assert set(AddresseeDecision.__annotations__) == {"addressee", "confidence", "channel", "reason_codes"}
        assert set(TaskSlots.__annotations__) == {
            "task_subtype",
            "query_rewrite",
            "time_range",
            "domain_hints",
            "source_prefs",
            "entity_hints",
            "speak_policy",
            "sub_asks",
            "readings_conflict",
        }

    def test_sub_ask_shape_is_frozen(self):
        assert set(SubAsk.__annotations__) == {
            "sub_ask_id",
            "span",
            "class_scores",
            "entity_hints",
            "domain_hints",
            "scope_ids",
            "time_range",
            "depends_on",
        }

    def test_gate_types_carry_no_plan_or_scope_fields(self):
        assert {"plan", "tool_args", "patient_id", "tenant_id"} <= FORBIDDEN_DECISION_KEYS
        for shape in (IntentDecision, AddresseeDecision, TaskSlots):
            assert not set(shape.__annotations__) & FORBIDDEN_DECISION_KEYS, shape.__name__

    def test_task_groups_and_lanes(self):
        assert not ASSIST_TASKS & JOB_TASKS
        assert ASSIST_TASKS | JOB_TASKS | {"unknown"} == set(TASK_SUBTYPES)
        assert set(TASK_LANE) == set(TASK_SUBTYPES)
        assert set(TASK_LANE.values()) <= set(LANES)

    def test_scribe_output_never_enters_gate(self):
        assert "Scribe" not in GATE_INPUT_SPEAKERS

    def test_status_model_includes_push_safety(self):
        assert "safety_alert_raised" in ENCOUNTER_STATUSES

    def test_valid_decisions_pass(self):
        explicit = _decision()
        explicit_with_sub_asks = _decision(task=_slots(sub_asks=[_sub_ask()]))
        ambient_silent = _decision(
            addressee=_addressee(addressee="patient", confidence=0.9, channel="ambient_transcript"),
            task=None,
            intervene=False,
            urgency="silent",
        )
        research_chip = _decision(
            addressee=_addressee(confidence=0.8, channel="ambient_transcript"),
            intervene=False,
            urgency="background",
        )
        for decision in (explicit, explicit_with_sub_asks, ambient_silent, research_chip):
            assert validate_intent_decision(decision) == []

    @pytest.mark.parametrize(
        "build, fragment",
        [
            (lambda: {**_decision(), "plan": ["retrieve_structured"]}, "gate must not emit"),
            (lambda: _decision(task={**_slots(), "tool_args": {}}), "gate must not emit"),
            (lambda: _decision(task={**_slots(), "patient_id": "p1"}), "gate must not emit"),
            (lambda: _decision(addressee=_addressee(addressee="nurse")), "addressee="),
            (lambda: _decision(addressee=_addressee(channel="sms")), "channel="),
            (lambda: _decision(addressee=_addressee(confidence=1.2)), "confidence"),
            (lambda: _decision(addressee=_addressee(addressee="patient")), "explicit channels imply"),
            (
                lambda: _decision(
                    addressee=_addressee(addressee="patient", channel="ambient_transcript"),
                    intervene=False,
                    urgency="silent",
                ),
                "task must be null",
            ),
            (lambda: _decision(task=None), "need TaskSlots"),
            (lambda: _decision(task=_slots(task_subtype="chitchat")), "task_subtype="),
            (lambda: _decision(task=_slots(source_prefs=["prior_labs_sql"])), "source_prefs not in contract"),
            (lambda: _decision(task=_slots(time_range=2)), "time_range must be"),
            (lambda: _decision(urgency="silent"), "intervene=true cannot"),
            (lambda: _decision(intervene=False), "intervene=false cannot"),
            (
                lambda: _decision(intervene=False, urgency="background", task=_slots(speak_policy="text_and_tts")),
                "text_and_tts",
            ),
            (lambda: _decision(task=_slots(sub_asks="not-a-list")), "sub_asks must be a list"),
            (lambda: _decision(task=_slots(readings_conflict="yes")), "readings_conflict must be bool"),
            (lambda: _decision(task=_slots(sub_asks=[{"garbage": True}])), "sub_asks[0] missing fields"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(class_scores={"made_up": 0.9})])), "unknown class"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(class_scores={"measurement": True})])), "must be a number"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(class_scores={"compile": 0.9})])), "unknown class"),
            (lambda: _decision(task=_slots(source_prefs=["prior_labs"])), "source_prefs not in contract"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(scope_ids="resp")])), "scope_ids must be a list"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(scope_ids=[""])])), "scope_ids must be a list"),
            (lambda: _decision(task=_slots(sub_asks=[_sub_ask(scope_ids=["a", "a"])])), "must not repeat"),
            (
                lambda: _decision(task=_slots(sub_asks=[
                    _sub_ask(sub_ask_id="a", depends_on=["b"]),
                    _sub_ask(sub_ask_id="b", depends_on=["a"]),
                ])),
                "acyclic",
            ),
        ],
    )
    def test_invalid_decision_is_rejected(self, build, fragment):
        errors = validate_intent_decision(build())
        assert any(fragment in e for e in errors), errors

    def test_missing_fields_are_reported(self):
        decision = _decision()
        del decision["urgency"]
        assert validate_intent_decision(decision) == ["missing fields: ['urgency']"]


@pytest.mark.unit
class TestInterventionPolicy:
    @pytest.mark.parametrize("addressee", ADDRESSEES)
    @pytest.mark.parametrize("task", _TASK_OPTIONS)
    @pytest.mark.parametrize("research", [False, True])
    @pytest.mark.parametrize("confidence", [0.0, 0.5, AMBIENT_CHIP_MIN_CONFIDENCE, 1.0])
    def test_ambient_never_intervenes(self, addressee, task, research, confidence):
        outcome = resolve_intervention(
            "ambient_transcript",
            addressee,
            task,
            addressee_confidence=confidence,
            ambient_research_enabled=research,
        )
        assert outcome["intervene"] is False
        assert outcome["mode"] in ("silent", "suggest_chip")

    @pytest.mark.parametrize("addressee", ADDRESSEES)
    @pytest.mark.parametrize("task", _TASK_OPTIONS)
    def test_ambient_is_silent_in_v1(self, addressee, task):
        outcome = resolve_intervention("ambient_transcript", addressee, task)
        assert outcome["mode"] == "silent"
        assert "ambient_v1_silent" in outcome["reason_codes"]

    def test_research_chip_needs_copilot_confidence_and_fixed_dispatch(self):
        def ambient(addressee, task, confidence=0.9, router_ok=True, dispatch="workflow"):
            return resolve_intervention(
                "ambient_transcript",
                addressee,
                task,
                addressee_confidence=confidence,
                router_ok=router_ok,
                ambient_research_enabled=True,
                dispatch=dispatch,
            )["mode"]

        assert ambient("copilot", "factoid") == "suggest_chip"
        assert ambient("copilot", "factoid", confidence=0.5) == "silent"
        assert ambient("patient", "factoid") == "silent"
        assert ambient("unknown", "factoid") == "silent"
        assert ambient("copilot", "session_control") == "silent"
        assert ambient("copilot", "unknown") == "silent"
        assert ambient("copilot", "factoid", router_ok=False) == "silent"
        assert ambient("copilot", "factoid", dispatch="clarify") == "silent"
        assert ambient("copilot", "factoid", dispatch="planning_agent") == "silent"
        assert ambient("copilot", "factoid", dispatch="fanout") == "suggest_chip"

    @pytest.mark.parametrize("channel", sorted(EXPLICIT_CHANNELS))
    @pytest.mark.parametrize("task", _TASK_OPTIONS)
    @pytest.mark.parametrize("router_ok", [True, False])
    def test_explicit_channels_are_never_silent(self, channel, task, router_ok):
        outcome = resolve_intervention(channel, "copilot", task, router_ok=router_ok)
        assert outcome["mode"] != "silent"

    def test_explicit_questions_answer_jobs_run_unclear_asks_clarify(self):
        assert resolve_intervention("explicit_ui", "copilot", "compare")["mode"] == "answer"
        assert resolve_intervention("explicit_ui", "copilot", "note")["mode"] == "job"
        assert resolve_intervention("explicit_ui", "copilot", "unknown")["mode"] == "clarify"
        assert resolve_intervention("explicit_ui", "copilot", None)["mode"] == "clarify"

    def test_voice_never_executes_session_control(self):
        assert resolve_intervention("wake_word", "copilot", "session_control")["mode"] == "suggest_chip"
        assert resolve_intervention("explicit_ui", "copilot", "session_control")["mode"] == "job"

    @pytest.mark.parametrize("channel", sorted(EXPLICIT_CHANNELS))
    def test_gate_failure_on_explicit_channel_falls_back_to_factoid_chain(self, channel):
        outcome = resolve_intervention(channel, "copilot", None, router_ok=False)
        assert outcome["mode"] == "answer"
        assert "default_factoid_chain" in outcome["reason_codes"]

    @pytest.mark.parametrize("channel", sorted(EXPLICIT_CHANNELS))
    @pytest.mark.parametrize("addressee", ["patient", "unknown"])
    def test_explicit_channel_requires_copilot_addressee(self, channel, addressee):
        with pytest.raises(ValueError):
            resolve_intervention(channel, addressee, "factoid")

    @pytest.mark.parametrize(
        "args",
        [
            ("sms", "copilot", "factoid"),
            ("explicit_ui", "nurse", "factoid"),
            ("explicit_ui", "copilot", "chitchat"),
        ],
    )
    def test_unknown_enum_values_raise(self, args):
        with pytest.raises(ValueError):
            resolve_intervention(*args)

    @pytest.mark.parametrize("channel", CHANNELS)
    @pytest.mark.parametrize("task", _TASK_OPTIONS)
    def test_tts_only_on_answers(self, channel, task):
        for addressee in _addressees_for(channel):
            outcome = resolve_intervention(
                channel, addressee, task, ambient_research_enabled=True, tts_enabled=True
            )
            if outcome["speak_policy"] == "text_and_tts":
                assert outcome["mode"] == "answer"
            if outcome["mode"] == "silent":
                assert outcome["speak_policy"] == "none"

    @pytest.mark.parametrize("channel", CHANNELS)
    @pytest.mark.parametrize("task", TASK_SUBTYPES)
    def test_outcomes_satisfy_decision_contract(self, channel, task):
        for addressee in _addressees_for(channel):
            outcome = resolve_intervention(
                channel, addressee, task, addressee_confidence=0.9, ambient_research_enabled=True
            )
            decision = _decision(
                addressee=_addressee(addressee=addressee, confidence=0.9, channel=channel),
                task=_slots(task_subtype=task, speak_policy=outcome["speak_policy"]) if addressee == "copilot" else None,
                intervene=outcome["intervene"],
                urgency=outcome["urgency"],
            )
            assert outcome["mode"] in INTERVENTION_MODES
            assert outcome["mode"] != "alert"
            assert validate_intent_decision(decision) == [], (channel, addressee, task)


@pytest.mark.unit
class TestExecutorContract:
    def test_dispatch_values_are_frozen(self):
        # planning_agent stays in the literal so the boundary is stable (SDD §9.2).
        assert set(DISPATCH_VALUES) == {"silent", "clarify", "workflow", "fanout", "planning_agent"}

    def test_closed_value_sets_are_frozen(self):
        assert set(CLARIFY_KINDS) == {"scope", "reading", "rephrase", "narrow"}
        assert PHYSICIAN_CHOICES == ("processed_pages", "reask", "none")
        assert OUTCOME_KINDS == ("completed", "clarification_needed", "planning_needed")
        assert ANSWER_STATUSES == ("answered", "refused", "clarifying", "still_processing")

    def test_provisional_constants_from_config(self):
        assert SUB_ASK_MIN_CONFIDENCE == 0.75
        assert MAX_FANOUT_WORKFLOWS == 3
        assert REFERENCE_RESOLUTION_WAIT_MS == 3000
        assert RECHECK_INTERVAL_MS == 1000
        assert POST_BARRIER_RESERVE_MS == 3300

    def test_fixed_materialization_wait_is_retired(self):
        assert not hasattr(agent_config, "QUERY_MATERIALIZATION_WAIT_MS")

    @pytest.mark.parametrize(
        "symbol",
        [
            "WorkflowState", "WorkerPlan", "PlanTask", "AgentStep", "validate_agent_step",
            "MAX_AGENT_TOOL_CALLS", "AGENT_WALL_CLOCK_BUDGET_MS", "ExecutorMode",
            "TASK_EXECUTOR_MODE", "FIXED_TOOL_CHAINS", "WORKFLOW_NAME",
        ],
    )
    def test_symbols_without_a_v1_reader_are_gone(self, symbol):
        assert not hasattr(executor_contract, symbol)

    def test_request_context_and_watermark_shapes(self):
        assert set(AssistRequestContext.__annotations__) == {
            "request_id", "session_id", "trace_id", "channel", "watermarks",
            "deadline_at", "resumes_answer_id", "patient_id", "clinician_id",
        }
        assert set(ReceiptWatermarks.__annotations__) == {
            "as_of_receipt", "snapshot_generation", "transcript_stream_id", "draft_version",
        }
        assert "tenant_id" not in AssistRequestContext.__annotations__

    def test_dispatch_decision_shape(self):
        assert set(DispatchDecision.__annotations__) == {
            "dispatch", "dispatch_rule", "clarify_kind", "reason_codes", "workflow_ids",
        }

    def test_clarify_request_and_scope_choice_shapes(self):
        assert set(ClarifyRequest.__annotations__) == {"kind", "choices", "allow_free_text"}
        assert set(ScopeChoice.__annotations__) == {
            "scope_id", "rank", "label", "supporting_citation_ids", "expands_to"
        }

    def test_plan_request_and_evidence_ref_shapes(self):
        assert set(PlanRequest.__dataclass_fields__) == {
            "workflow_id", "reason", "goal", "scope", "unmet_requirements", "evidence_ref",
        }
        assert set(EvidenceRef.__dataclass_fields__) == {"bundle_id", "receipt_ids", "citation_ids"}

    def test_assist_answer_shape(self):
        assert set(AssistAnswer.__annotations__) == {
            "answer_id", "request_id", "session_id", "status", "claims", "cited",
            "bundle_ref", "grounding", "clarify", "coverage", "watermarks",
            "resumes_answer_id", "created_at",
        }
        assert "supersedes_answer_id" not in AssistAnswer.__annotations__

    def test_valid_request_context_passes(self):
        assert validate_request_context(_context()) == []
        assert validate_request_context(_context(watermarks=_watermarks(draft_version=None))) == []

    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"request_id": ""}, "context.request_id"),
            ({"clinician_id": None}, "context.clinician_id"),
            ({"channel": "sms"}, "context.channel"),
            ({"deadline_at": "soon"}, "deadline_at"),
            ({"deadline_at": "2026-09-30T12:00:08"}, "deadline_at"),
            ({"deadline_at": "2026-09-30T11:59:00+00:00"}, "later than"),
            ({"resumes_answer_id": ""}, "resumes_answer_id"),
            ({"watermarks": _watermarks(snapshot_generation=-1)}, "snapshot_generation"),
            ({"watermarks": _watermarks(as_of_receipt="yesterday")}, "as_of_receipt"),
            ({"watermarks": {"as_of_receipt": "2026-09-30T12:00:00+00:00"}}, "watermarks fields"),
            ({"tenant_id": "t1"}, "unknown fields"),
        ],
    )
    def test_invalid_request_context_is_rejected(self, overrides, fragment):
        errors = validate_request_context(_context(**overrides))
        assert any(fragment in e for e in errors), errors

    def test_request_context_reports_missing_fields(self):
        context = _context()
        del context["deadline_at"]
        assert validate_request_context(context) == ["request context missing fields: ['deadline_at']"]
        assert validate_request_context("ctx") == ["request context must be an object"]

    @pytest.mark.parametrize(
        "evidence_class, workflow_id",
        [
            ("measurement", "measurement"),
            ("safety", "safety"),
            ("general", "general_cascade"),
            ("note", "jobs"),
            ("session_control", "jobs"),
        ],
    )
    def test_workflow_ids_follow_evidence_class(self, evidence_class, workflow_id):
        assert workflow_id_for(evidence_class) == workflow_id

    @pytest.mark.parametrize("evidence_class", ["no_workflow", "compile", "factoid"])
    def test_classes_without_a_fixed_workflow_are_rejected(self, evidence_class):
        with pytest.raises(ContractViolationError):
            workflow_id_for(evidence_class)

    def test_any_unsupported_claim_blocks_rendering(self):
        assert grounding_verdict([]) == "render"
        assert grounding_verdict(["claim-2"]) == "refuse"


def _bundle_with_result():
    bundle = new_bundle("bundle-1")
    append_result(bundle, _tool_result())
    return bundle


def _plan_request(**overrides):
    fields = {
        "workflow_id": "trajectory",
        "reason": "missing_comparison_side",
        "goal": "trend of RBC over two years",
        "scope": (_sub_ask(),),
        "unmet_requirements": ("observation:rbc:2024",),
        "evidence_ref": make_evidence_ref(_bundle_with_result()),
    }
    fields.update(overrides)
    return PlanRequest(**fields)


@pytest.mark.unit
class TestWorkflowOutcome:
    def test_union_is_closed_and_exhaustive(self):
        members = get_args(WorkflowOutcome)
        tags = {get_args(get_type_hints(member)["kind"])[0] for member in members}
        assert tags == set(OUTCOME_KINDS) == set(OUTCOME_PAYLOAD)
        for member in members:
            hints = get_type_hints(member)
            kind = get_args(hints["kind"])[0]
            assert set(hints) == {"kind", OUTCOME_PAYLOAD[kind]}, member.__name__

    def test_each_outcome_kind_validates(self):
        clarify = {"kind": "scope", "choices": [], "allow_free_text": True}
        assert validate_workflow_outcome({"kind": "completed", "bundle": _bundle_with_result()}) == []
        assert validate_workflow_outcome({"kind": "clarification_needed", "clarify": clarify}) == []
        assert validate_workflow_outcome({"kind": "planning_needed", "plan_request": _plan_request()}) == []

    @pytest.mark.parametrize(
        "outcome, fragment",
        [
            ("done", "must be an object"),
            ({"kind": "needs_plan"}, "outcome.kind"),
            ({"kind": "completed", "bundle": {}, "clarify": None}, "exactly"),
            ({"kind": "completed", "bundle": {"bundle_id": "b"}}, "EvidenceBundle"),
            ({"kind": "planning_needed", "plan_request": {"goal": "x"}}, "PlanRequest"),
            ({"kind": "clarification_needed", "clarify": {"kind": "vague", "choices": [], "allow_free_text": True}}, "clarify.kind"),
        ],
    )
    def test_invalid_outcome_is_rejected(self, outcome, fragment):
        errors = validate_workflow_outcome(outcome)
        assert any(fragment in e for e in errors), errors


@pytest.mark.unit
class TestPlanRequest:
    def test_evidence_ref_snapshots_the_bundle(self):
        bundle = _bundle_with_result()
        ref = make_evidence_ref(bundle)
        assert ref.bundle_id == "bundle-1"
        assert ref.receipt_ids == ("invoke-1",)
        assert ref.citation_ids == (OBS_123,)

        # The bundle keeps growing; the ref does not.
        append_result(bundle, _receipted(_tool_result(citations=[_citation(source_id="obs-9")]), "invoke-2", "b" * 64))
        assert ref.receipt_ids == ("invoke-1",)

    def test_plan_request_is_immutable(self):
        request = _plan_request()
        with pytest.raises(FrozenInstanceError):
            request.goal = "something else"
        with pytest.raises(FrozenInstanceError):
            request.evidence_ref.bundle_id = "other"

    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"scope": (_sub_ask(entity_hints=[], patient_id="p1"),)}, "scope"),
            ({"scope": (_sub_ask(clinician_id="c1"),)}, "scope"),
            ({"scope": ()}, "PlanRequest.scope"),
            ({"scope": [_sub_ask()]}, "PlanRequest.scope"),
            ({"goal": ""}, "PlanRequest.goal"),
            ({"unmet_requirements": ()}, "unmet_requirements"),
            ({"unmet_requirements": ["x"]}, "unmet_requirements"),
            ({"evidence_ref": {"bundle_id": "b"}}, "evidence_ref"),
        ],
    )
    def test_invalid_plan_request_is_rejected(self, overrides, fragment):
        with pytest.raises(ContractViolationError) as exc:
            _plan_request(**overrides)
        assert fragment in str(exc.value)

    def test_plan_request_rejects_scope_keys_on_sub_asks(self):
        sub_ask = _sub_ask()
        sub_ask["class_scores"] = {"measurement": 0.9}
        with pytest.raises(ContractViolationError):
            _plan_request(scope=({**sub_ask, "session_id": "s1"},))

    def test_plan_request_carries_no_cutoff_deadline_or_sources(self):
        fields = set(PlanRequest.__dataclass_fields__)
        assert not fields & {"as_of_receipt", "deadline_at", "latency_remaining_ms", "sources_checked", "acquired"}

    def test_evidence_ref_rejects_lists(self):
        with pytest.raises(ContractViolationError):
            EvidenceRef(bundle_id="b", receipt_ids=["r"], citation_ids=())


@pytest.mark.unit
class TestAssistAnswer:
    def test_valid_answers_pass(self):
        assert validate_assist_answer(_answer()) == []
        refused = _answer(
            status="refused",
            grounding={"claims_checked": 1, "unsupported_claim_ids": ["c-1"], "verdict": "refuse"},
        )
        assert validate_assist_answer(refused) == []
        clarifying = _answer(
            status="clarifying", claims=[], cited=[], bundle_ref=None, grounding=None,
            clarify={"kind": "scope", "choices": [], "allow_free_text": True},
        )
        assert validate_assist_answer(clarifying) == []
        still_processing = _answer(
            status="still_processing", claims=[], cited=[], grounding=None,
            coverage={
                "requirements": [_requirement(status="pending")],
                "unreferenced_inflight_doc_ids": [],
                "partial_sources": [],
            },
        )
        assert validate_assist_answer(still_processing) == []

    def test_cited_is_the_closure_of_claims_and_derivations(self):
        derivation = {
            "operation": "compute_delta",
            "input_citation_ids": [OBS_123, OBS_9],
            "receipt_id": "invoke-3",
        }
        claims = [_claim(derivation=derivation)]
        cited = [_citation(), _citation(source_id="obs-9")]
        assert validate_assist_answer(_answer(claims=claims, cited=cited)) == []

        errors = validate_assist_answer(_answer(claims=claims, cited=[_citation()]))
        assert any(f"missing=['{OBS_9}']" in e for e in errors), errors

    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"cited": [_citation(), _citation(source_id="obs-extra")]}, "extra=['observation:obs-extra#observations/obs-extra/value']"),
            ({"cited": [_citation(), _citation()]}, "more than once"),
            ({"status": "done"}, "answer.status"),
            ({"status": "answered", "grounding": {"claims_checked": 1, "unsupported_claim_ids": ["c-1"], "verdict": "refuse"}}, "verdict 'render'"),
            ({"grounding": None}, "GroundingReport"),
            ({"bundle_ref": None}, "reference its bundle"),
            ({"clarify": {"kind": "scope", "choices": [], "allow_free_text": True}}, "clarify must be null"),
            ({"resumes_answer_id": "ans-1"}, "must not equal"),
            ({"created_at": "now"}, "created_at"),
            ({"watermarks": _watermarks(snapshot_generation="3")}, "snapshot_generation"),
            ({"cited": [{**_citation(), "citation_id": "obs-123"}]}, "citation_id"),
        ],
    )
    def test_invalid_answer_is_rejected(self, overrides, fragment):
        errors = validate_assist_answer(_answer(**overrides))
        assert any(fragment in e for e in errors), errors

    def test_still_processing_must_name_an_unmet_document(self):
        all_met = {"requirements": [_requirement()], "unreferenced_inflight_doc_ids": [], "partial_sources": []}
        errors = validate_assist_answer(
            _answer(status="still_processing", claims=[], cited=[], grounding=None, coverage=all_met)
        )
        assert any("unmet requirement" in e for e in errors), errors
        errors = validate_assist_answer(
            _answer(status="still_processing", claims=[], cited=[], grounding=None, coverage=None)
        )
        assert any("must carry coverage" in e for e in errors), errors

    def test_clarifying_answer_needs_a_structured_request(self):
        errors = validate_assist_answer(
            _answer(status="clarifying", claims=[], cited=[], grounding=None, clarify=None)
        )
        assert any("clarify fields" in e for e in errors), errors

    def test_missing_fields_are_reported(self):
        answer = _answer()
        del answer["watermarks"]
        assert validate_assist_answer(answer) == ["answer missing fields: ['watermarks']"]


@pytest.mark.unit
class TestDispatchAssist:
    """dispatch_assist() is a pure function; all branches tested directly."""

    def _slots_with(self, sub_asks=None, readings_conflict=False):
        return {
            "sub_asks": sub_asks or [],
            "readings_conflict": readings_conflict,
        }

    def _dispatch(self, sub_asks=None, channel="explicit_ui", readings_conflict=False):
        return dispatch_assist(_context(channel=channel), self._slots_with(sub_asks, readings_conflict))

    def test_ambient_is_always_silent(self):
        for sub_asks in ([], [_sub_ask()]):
            decision = self._dispatch(sub_asks, channel="ambient_transcript")
            assert decision == {
                "dispatch": "silent", "dispatch_rule": 1, "clarify_kind": None,
                "reason_codes": ["ambient_v1_silent"], "workflow_ids": [],
            }

    def test_no_sub_asks_triggers_clarify(self):
        decision = self._dispatch([])
        assert (decision["dispatch"], decision["dispatch_rule"], decision["clarify_kind"]) == ("clarify", 2, "rephrase")

    def test_no_accepted_class_triggers_clarify(self):
        decision = self._dispatch([_sub_ask(class_scores={"measurement": 0.50})])  # below threshold
        assert (decision["dispatch"], decision["clarify_kind"]) == ("clarify", "rephrase")
        assert "no_accepted_class" in decision["reason_codes"]

    def test_underspecified_triggers_scope_clarify(self):
        decision = self._dispatch([_sub_ask(entity_hints=[], domain_hints=[], class_scores={"session": 0.90})])
        assert (decision["dispatch"], decision["clarify_kind"]) == ("clarify", "scope")

    def test_scope_ids_specify_a_sub_ask(self):
        sa = _sub_ask(entity_hints=[], domain_hints=[], scope_ids=["respiratory"], class_scores={"trajectory": 0.9})
        assert self._dispatch([sa])["dispatch"] == "workflow"

    def test_job_sub_ask_needs_no_hints(self):
        sa = _sub_ask(entity_hints=[], domain_hints=[], class_scores={"note": 0.95})
        decision = self._dispatch([sa])
        assert (decision["dispatch"], decision["workflow_ids"]) == ("workflow", ["jobs"])

    def test_readings_conflict_triggers_reading_clarify(self):
        decision = self._dispatch([_sub_ask()], readings_conflict=True)
        assert (decision["dispatch"], decision["clarify_kind"]) == ("clarify", "reading")

    def test_depends_on_maps_to_clarify_and_logs_needs_plan(self, caplog):
        sub_asks = [_sub_ask(sub_ask_id="sa-0"), _sub_ask(sub_ask_id="sa-1", depends_on=["sa-0"])]
        with caplog.at_level("WARNING", logger="app.agents.intent.executor_contract"):
            decision = self._dispatch(sub_asks)
        assert (decision["dispatch"], decision["dispatch_rule"], decision["clarify_kind"]) == ("clarify", 3, "narrow")
        assert decision["reason_codes"] == ["needs_plan", "depends_on"]
        assert any("needs_plan" in r.getMessage() for r in caplog.records)

    def test_no_workflow_class_maps_to_clarify_rule_3(self):
        decision = self._dispatch([_sub_ask(class_scores={"no_workflow": 0.85})])
        assert (decision["dispatch"], decision["dispatch_rule"], decision["clarify_kind"]) == ("clarify", 3, "rephrase")
        assert "no_workflow" in decision["reason_codes"]

    def test_one_independent_sub_ask_triggers_workflow(self):
        decision = self._dispatch([_sub_ask(class_scores={"measurement": 0.92})])
        assert decision == {
            "dispatch": "workflow", "dispatch_rule": 4, "clarify_kind": None,
            "reason_codes": ["single_workflow"], "workflow_ids": ["measurement"],
        }

    def test_two_independent_sub_asks_trigger_fanout(self):
        sa1 = _sub_ask(sub_ask_id="sa-1", entity_hints=["rbc"], class_scores={"measurement": 0.92})
        sa2 = _sub_ask(sub_ask_id="sa-2", entity_hints=["sodium"], class_scores={"safety": 0.88})
        decision = self._dispatch([sa1, sa2])
        assert (decision["dispatch"], decision["dispatch_rule"]) == ("fanout", 5)
        assert decision["workflow_ids"] == ["measurement", "safety"]

    def test_over_max_fanout_triggers_narrow_clarify(self):
        sub_asks = [
            _sub_ask(sub_ask_id=f"sa-{i}", entity_hints=[f"lab-{i}"], class_scores={"measurement": 0.90})
            for i in range(MAX_FANOUT_WORKFLOWS + 1)
        ]
        decision = self._dispatch(sub_asks)
        assert (decision["dispatch"], decision["dispatch_rule"], decision["clarify_kind"]) == ("clarify", 6, "narrow")

    def test_exactly_max_fanout_triggers_fanout(self):
        sub_asks = [
            _sub_ask(sub_ask_id=f"sa-{i}", entity_hints=[f"lab-{i}"], class_scores={"measurement": 0.90})
            for i in range(MAX_FANOUT_WORKFLOWS)
        ]
        assert self._dispatch(sub_asks)["dispatch"] == "fanout"

    def test_wake_word_follows_same_rules(self):
        assert self._dispatch([_sub_ask()], channel="wake_word")["dispatch"] == "workflow"
        assert self._dispatch([], channel="wake_word")["dispatch"] == "clarify"

    def test_multiple_accepted_classes_on_one_sub_ask_fan_out(self):
        decision = self._dispatch([_sub_ask(class_scores={"measurement": 0.92, "document": 0.86})])
        assert (decision["dispatch"], decision["workflow_ids"]) == ("fanout", ["measurement", "document"])

    def test_clarify_kind_is_set_iff_dispatch_is_clarify(self):
        cases = [
            [], [_sub_ask()], [_sub_ask(class_scores={"no_workflow": 0.9})],
            [_sub_ask(class_scores={"measurement": 0.92, "document": 0.86})],
        ]
        for sub_asks in cases:
            decision = self._dispatch(sub_asks)
            assert (decision["clarify_kind"] is not None) == (decision["dispatch"] == "clarify"), decision
            assert decision["dispatch"] != "planning_agent"

    @pytest.mark.parametrize(
        "context, slots, fragment",
        [
            (_context(channel="sms"), {"sub_asks": [], "readings_conflict": False}, "request context"),
            (_context(deadline_at=None), {"sub_asks": [], "readings_conflict": False}, "deadline_at"),
            (_context(), "slots", "TaskSlots"),
            (_context(), {"sub_asks": None, "readings_conflict": False}, "slots.sub_asks"),
            (_context(), {"sub_asks": [], "readings_conflict": "no"}, "readings_conflict"),
            (_context(), {"sub_asks": [{"garbage": True}], "readings_conflict": False}, "sub_asks"),
            (
                _context(),
                {"sub_asks": [_sub_ask(depends_on=["sa-missing"])], "readings_conflict": False},
                "unknown sub_ask",
            ),
        ],
    )
    def test_invalid_input_is_rejected(self, context, slots, fragment):
        with pytest.raises(ContractViolationError) as exc:
            dispatch_assist(context, slots)
        assert fragment in str(exc.value)


@pytest.mark.unit
class TestSharedToolRegistry:
    def test_tool_ids_stages_and_callers_are_frozen(self):
        assert TOOL_IDS == (
            "retrieve_session",
            "retrieve_structured",
            "retrieve_source_chunks",
            "get_patient_profile",
            "retrieve_docs",
            "retrieve_visits",
            "retrieve_for_candidates",
            "ingest_delta",
            "compare_findings",
            "generate_note",
            "check_med_conflicts",
            "check_dosage",
            "check_metric_alerts",
            "normalize_units",
            "compute_trend",
            "compute_delta",
        )
        assert LANE_B_STAGES == (
            "ingest_delta",
            "compile_candidates",
            "enrich",
            "materialize_record",
            "safety_and_validate",
            "finalize",
        )
        assert TOOL_CALLERS == ("lane_b_stage", "fixed_executor", "planning_agent")

    def test_every_tool_has_a_spec_within_contract(self):
        assert set(TOOL_SPECS) == set(TOOL_IDS)
        for tool_id, spec in TOOL_SPECS.items():
            assert spec["writes"] in TOOL_WRITES, tool_id
            assert set(spec["lane_b_stages"]) <= set(LANE_B_STAGES), tool_id
            if spec["planner_allowlisted"]:
                assert spec["assist_callable"], tool_id

    def test_no_tool_can_write_postgres(self):
        assert TOOL_WRITES == ("none", "session_scratch", "session_draft")

    def test_retrieve_labs_is_retired(self):
        assert "retrieve_labs" not in TOOL_IDS
        assert "retrieve_labs" not in TOOL_SPECS

    def test_safety_check_is_retired(self):
        assert "safety_check" not in TOOL_IDS
        assert "safety_check" not in TOOL_SPECS

    def test_retrieval_is_shared_by_lane_b_fixed_chains_and_planner(self):
        for tool_id in ("retrieve_session", "retrieve_structured", "retrieve_docs", "retrieve_visits"):
            spec = TOOL_SPECS[tool_id]
            assert spec["assist_callable"], tool_id
            assert spec["planner_allowlisted"], tool_id
            assert "enrich" in spec["lane_b_stages"], tool_id
            assert spec["requires_citations"], tool_id

    def test_compute_tools_are_planner_allowlisted_and_lane_b_free(self):
        for tool_id in ("normalize_units", "compute_trend", "compute_delta"):
            spec = TOOL_SPECS[tool_id]
            assert spec["planner_allowlisted"], tool_id
            assert spec["lane_b_stages"] == (), tool_id
            assert not spec["requires_citations"], tool_id

    def test_safety_tools_are_assist_callable_but_not_planner_allowlisted(self):
        for tool_id in ("check_med_conflicts", "check_dosage", "check_metric_alerts"):
            spec = TOOL_SPECS[tool_id]
            assert spec["assist_callable"], tool_id
            assert not spec["planner_allowlisted"], tool_id
            assert "safety_and_validate" in spec["lane_b_stages"], tool_id

    def test_agent_allowlist_alias_is_gone(self):
        from app.agents import tool_contracts
        assert not hasattr(tool_contracts, "AGENT_ALLOWLIST")

    def test_ingest_delta_is_a_lane_b_stage_only(self):
        spec = TOOL_SPECS["ingest_delta"]
        assert not spec["assist_callable"]
        assert not spec["planner_allowlisted"]
        assert spec["lane_b_stages"] == ("ingest_delta",)

    def test_planner_allowlist_is_read_and_scratch_only(self):
        assert all(TOOL_SPECS[t]["writes"] in ("none", "session_scratch") for t in PLANNER_ALLOWLIST)

    def test_note_generation_is_neither_a_compile_stage_nor_planner_tool(self):
        spec = TOOL_SPECS["generate_note"]
        assert spec["lane_b_stages"] == ()
        assert spec["assist_callable"]
        assert not spec["planner_allowlisted"]

    def test_scope_is_injected_never_model_supplied(self):
        assert SCOPE_ARG_KEYS == {"patient_id", "clinician_id", "session_id", "tenant_id"}
        assert "doctor_id" not in SCOPE_ARG_KEYS
        assert any("clinician_id" in e for e in validate_model_tool_args("retrieve_docs", {"clinician_id": "c"}))
        errors = validate_model_tool_args("retrieve_structured", {"items": [{"patient_id": "p1"}]})
        assert any("items[0].patient_id" in e for e in errors), errors
        assert validate_model_tool_args("retrieve_structured", {"kind": "lab_result", "analyte": "rbc"}) == []

    def test_evidence_state_values_are_frozen(self):
        assert EVIDENCE_STATES == ("received", "materialized", "validated", "authorized")

    def test_source_kinds_name_what_a_source_is(self):
        assert SOURCE_KINDS == (
            "session_transcript", "session_draft", "patient_snapshot",
            "document", "observation", "visit",
        )

    def test_citation_shape_includes_1_2_fields(self):
        assert set(Citation.__annotations__) == {
            "citation_id", "source_kind", "source_id", "snippet", "observed_at",
            "received_at", "evidence_state", "locator", "score",
        }

    def test_locator_union_is_tagged_on_kind(self):
        assert set(DocumentSpan.__annotations__) == {"kind", "doc_id", "chunk_id", "page", "char_start", "char_end"}
        assert set(TranscriptSpan.__annotations__) == {"kind", "segment_id", "t_start", "t_end"}
        assert set(RowRef.__annotations__) == {"kind", "table", "row_id", "column"}
        assert LOCATOR_KIND_BY_SOURCE == {
            "document": "document_span",
            "session_transcript": "transcript_span",
            "observation": "row_ref",
            "visit": "row_ref",
        }

    def test_citation_id_names_the_span_not_the_source(self):
        page_1 = {"kind": "document_span", "doc_id": "doc-7", "chunk_id": "c1", "page": 1, "char_start": 0, "char_end": 40}
        page_2 = {**page_1, "chunk_id": "c2", "page": 2}
        assert make_citation_id("document", "doc-7", page_1) == "document:doc-7#c1:0-40"
        assert make_citation_id("document", "doc-7", page_1) != make_citation_id("document", "doc-7", page_2)
        segment = {"kind": "transcript_span", "segment_id": "seg-1", "t_start": 1.0, "t_end": 2.5}
        assert make_citation_id("session_transcript", "seg-1", segment) == "session_transcript:seg-1#seg-1:1000-2500"
        row = {"kind": "row_ref", "table": "visits", "row_id": "v-1", "column": None}
        assert make_citation_id("visit", "v-1", row) == "visit:v-1#visits/v-1/"
        assert make_citation_id("patient_snapshot", "rec-1#v4") == "patient_snapshot:rec-1#v4"

    @pytest.mark.parametrize(
        "args",
        [
            ("uploaded_doc", "doc-7", None),
            ("document", "", None),
            ("document", "doc-7", None),
            ("document", "doc-7", {"kind": "document_span", "doc_id": "doc-8", "chunk_id": "c", "page": 1, "char_start": 0, "char_end": 4}),
            ("patient_snapshot", "rec-1", {"kind": "row_ref", "table": "t", "row_id": "rec-1", "column": None}),
        ],
    )
    def test_citation_id_builder_rejects_bad_input(self, args):
        with pytest.raises(ContractViolationError):
            make_citation_id(*args)

    @pytest.mark.parametrize("source_kind", ["observation", "visit", "document", "session_transcript", "session_draft"])
    def test_each_source_kind_takes_its_locator(self, source_kind):
        citation = _citation(source_kind, "src-1")
        receipt = {**_tool_result()["receipt"], "tool_id": "retrieve_docs"}
        assert validate_tool_result(_tool_result(tool_id="retrieve_docs", citations=[citation], receipt=receipt)) == []

    def test_claim_and_derivation_shapes(self):
        assert set(Claim.__annotations__) == {
            "claim_id", "text", "claim_type", "value", "unit", "date",
            "negated", "citation_ids", "derivation", "evidence_state",
        }
        assert set(Derivation.__annotations__) == {"operation", "input_citation_ids", "receipt_id"}

    def test_not_covered_error_is_defined(self):
        assert NOT_COVERED_ERROR == "not_covered"

    def test_grounded_result_passes(self):
        assert validate_tool_result(_tool_result()) == []

    def test_no_source_miss_is_valid(self):
        receipt = {**_tool_result()["receipt"], "ok": False, "error": NO_SOURCE_ERROR}
        miss = _tool_result(
            tool_id="retrieve_structured", ok=False, data={}, citations=[],
            error=NO_SOURCE_ERROR, receipt=receipt,
        )
        assert validate_tool_result(miss) == []

    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"citations": []}, "ungrounded"),
            ({"tool_id": "compare_findings", "citations": []}, "ungrounded"),
            ({"citations": [{**_tool_result()["citations"][0], "source_kind": "web"}]}, "source_kind"),
            ({"citations": [{**_tool_result()["citations"][0], "source_id": ""}]}, "source_id"),
            ({"citations": [{"source_kind": "observation", "source_id": "x"}]}, "missing fields"),
            ({"citations": [_citation(source_kind="prior_labs")]}, "source_kind"),
            ({"citations": [_citation(citation_id="obs-123")]}, "citation_id"),
            ({"citations": [_citation(citation_id="observation:chunk-9")]}, "citation_id"),
            ({"citations": [_citation(locator=None)]}, "row_ref"),
            ({"citations": [_citation(locator={"kind": "row_ref", "table": "observations", "row_id": "other", "column": None})]}, "row_id"),
            ({"citations": [_citation("document", "doc-1", locator={"page": 1, "char_start": 0, "char_end": 4})]}, "document_span"),
            ({"citations": [_citation("document", "doc-1", locator={"kind": "document_span", "doc_id": "doc-2", "chunk_id": "c", "page": 1, "char_start": 0, "char_end": 4})]}, "doc_id"),
            ({"citations": [_citation("document", "doc-1", locator={"kind": "document_span", "doc_id": "doc-1", "chunk_id": "", "page": 1, "char_start": 0, "char_end": 4})]}, "chunk_id"),
            ({"citations": [_citation("document", "doc-1", locator={"kind": "document_span", "doc_id": "doc-1", "chunk_id": "c", "page": 0, "char_start": 0, "char_end": 4})]}, "ordered"),
            ({"citations": [_citation("session_transcript", "seg-1", locator={"kind": "transcript_span", "segment_id": "seg-1", "t_start": 3.0, "t_end": 1.0})]}, "ordered"),
            ({"citations": [_citation("session_draft", "d-1", locator={"kind": "row_ref", "table": "t", "row_id": "d-1", "column": None})]}, "must be null"),
            ({"ok": False, "error": None}, "error string"),
            ({"tool_id": "retrieve_everything"}, "unknown tool"),
            ({"data": []}, "data must be an object"),
            ({"receipt": None}, "receipt must be an object"),
        ],
    )
    def test_invalid_tool_result_is_rejected(self, overrides, fragment):
        errors = validate_tool_result(_tool_result(**overrides))
        assert any(fragment in e for e in errors), errors

    def test_safety_tools_may_return_without_citations(self):
        for tool_id in ("check_med_conflicts", "check_dosage", "check_metric_alerts"):
            receipt = {**_tool_result()["receipt"], "tool_id": tool_id}
            result = _tool_result(tool_id=tool_id, citations=[], data={"alerts": []}, receipt=receipt)
            assert validate_tool_result(result) == [], tool_id

    def test_receipt_carries_args_hash_not_raw_args(self):
        fields = set(ToolInvocationReceipt.__annotations__)
        assert "args_hash" in fields
        assert not fields & {"args", "text", "query", "patient_id"}
        assert {"caller", "caller_ref", "cache_hit", "source_refs"} <= fields

    def test_caller_is_planning_agent_not_bounded_agent(self):
        assert "planning_agent" in TOOL_CALLERS
        assert "bounded_agent" not in TOOL_CALLERS


@pytest.mark.unit
class TestEvidenceBundle:
    def test_bundle_and_coverage_shapes(self):
        assert set(EvidenceBundle.__annotations__) == {
            "bundle_id", "results", "citations", "sources_checked", "coverage", "closed",
        }
        assert set(CoverageBanner.__annotations__) == {
            "requirements", "unreferenced_inflight_doc_ids", "partial_sources",
        }
        assert set(RequirementOutcome.__annotations__) == {"doc_id", "need", "status", "failure_code"}
        assert INGEST_LEVELS == ("received", "described", "indexed", "facts")
        assert REQUIREMENT_STATUSES == ("met", "unmet_terminal", "pending")
        assert FAILURE_CODES == ("unreadable_file", "ocr_failed", "extraction_failed", "timeout")

    def test_append_indexes_citations_and_sources(self):
        bundle = new_bundle("bundle-1")
        assert append_result(bundle, _tool_result()) is True
        second = _receipted(
            _tool_result(citations=[_citation(), _citation(source_id="obs-9")]), "invoke-2", "b" * 64
        )
        assert append_result(bundle, second) is True
        assert list(bundle["citations"]) == [OBS_123, OBS_9]
        assert bundle["sources_checked"] == ["retrieve_structured:" + "a" * 64, "retrieve_structured:" + "b" * 64]
        assert len(bundle["results"]) == 2

    def test_duplicate_tool_run_is_dropped_and_logged(self, caplog):
        bundle = new_bundle("bundle-1")
        append_result(bundle, _tool_result())
        with caplog.at_level("WARNING", logger="app.agents.tool_contracts"):
            assert append_result(bundle, _receipted(_tool_result(), "invoke-2", "a" * 64)) is False
        assert len(bundle["results"]) == 1
        assert any("duplicate tool run" in r.getMessage() for r in caplog.records)

    def test_bundle_rejects_appends_after_close(self):
        bundle = new_bundle("bundle-1")
        append_result(bundle, _tool_result())
        close_bundle(bundle, empty_coverage())
        assert bundle["closed"] is True
        with pytest.raises(BundleClosedError):
            append_result(bundle, _receipted(_tool_result(), "invoke-2", "b" * 64))
        with pytest.raises(BundleClosedError):
            close_bundle(bundle, empty_coverage())
        assert len(bundle["results"]) == 1

    def test_bundle_rejects_invalid_results(self):
        bundle = new_bundle("bundle-1")
        with pytest.raises(ContractViolationError):
            append_result(bundle, _tool_result(citations=[]))
        assert bundle["results"] == [] and bundle["sources_checked"] == []

    @pytest.mark.parametrize("bundle_id", ["", None, 7])
    def test_bundle_id_is_required(self, bundle_id):
        with pytest.raises(ContractViolationError):
            new_bundle(bundle_id)

    def test_close_records_coverage(self):
        coverage = {
            "requirements": [
                _requirement("doc-1"),
                _requirement("doc-2", status="unmet_terminal", failure_code="ocr_failed"),
            ],
            "unreferenced_inflight_doc_ids": ["doc-3"],
            "partial_sources": [],
        }
        assert close_bundle(new_bundle("b"), coverage)["coverage"] == coverage

    @pytest.mark.parametrize(
        "requirement, fragment",
        [
            (_requirement(status="unmet_terminal"), "failure_code"),
            (_requirement(failure_code="timeout"), "failure_code must be null"),
            (_requirement(need="parsed"), "need="),
            (_requirement(status="deferred"), "status="),
            (_requirement(doc_id=""), "doc_id"),
            ({"doc_id": "d"}, "fields must be"),
        ],
    )
    def test_close_rejects_invalid_coverage(self, requirement, fragment):
        coverage = {"requirements": [requirement], "unreferenced_inflight_doc_ids": [], "partial_sources": []}
        with pytest.raises(ContractViolationError) as exc:
            close_bundle(new_bundle("b"), coverage)
        assert fragment in str(exc.value)

    def test_close_rejects_duplicate_requirement(self):
        coverage = {"requirements": [_requirement(), _requirement()], "unreferenced_inflight_doc_ids": [], "partial_sources": []}
        with pytest.raises(ContractViolationError):
            close_bundle(new_bundle("b"), coverage)


@pytest.mark.unit
class TestLaneBContracts:
    def test_fact_statuses_and_review_states_are_frozen(self):
        assert FACT_STATUSES == ("active", "superseded", "retracted", "needs_review")
        assert REVIEW_STATES == ("working_draft", "open_review", "approved_pending_write", "persisted")

    def test_make_fact_key_normalizes(self):
        assert make_fact_key("allergy", "Amoxicillin") == "allergy:amoxicillin"
        assert make_fact_key("lab", "RBC", "2024-11-02") == "lab:rbc:2024-11-02"
        assert make_fact_key("vital", "Blood Pressure") == "vital:blood_pressure"

    @pytest.mark.parametrize("args", [(), ("allergy",), ("allergy", ""), ("", "amoxicillin"), ("allergy", "  ")])
    def test_make_fact_key_rejects_empty_parts(self, args):
        with pytest.raises(ValueError):
            make_fact_key(*args)

    def test_supersede_keeps_history(self):
        prior = _fact("allergy:penicillin", "f1")
        superseded = supersede(prior, "f2")
        retracted = supersede(prior, "f2", retracted=True)

        assert prior["status"] == "active"
        assert superseded["status"] == "superseded"
        assert retracted["status"] == "retracted"
        assert superseded["superseded_by"] == retracted["superseded_by"] == "f2"
        assert superseded["provenance"] == prior["provenance"]
        assert fact_source_ids(superseded, "session_transcript") == ["seg-f1"]

    def test_supersede_rejects_already_replaced_fact(self):
        already_replaced = _fact("allergy:penicillin", "f1", status="superseded")
        with pytest.raises(ValueError):
            supersede(already_replaced, "f3")

    def test_self_correction_leaves_one_active_fact(self):
        penicillin = _fact("allergy:penicillin", "f1")
        amoxicillin = _fact("allergy:amoxicillin", "f2")
        facts = [supersede(penicillin, "f2", retracted=True), amoxicillin]

        assert duplicate_active_keys(facts) == []
        assert [f["status"] for f in facts] == ["retracted", "active"]

    def test_fact_source_ids_read_provenance_evidence(self):
        fact = _fact("lab:rbc", "f1")
        fact["provenance"]["evidence"] += [
            _citation("document", "doc-1"),
            _citation("document", "doc-1"),
            _citation("document", "doc-2"),
        ]
        assert fact_source_ids(fact, "document") == ["doc-1", "doc-2"]
        assert fact_source_ids(fact, "visit") == []
        with pytest.raises(ContractViolationError):
            fact_source_ids(fact, "prior_docs")
        with pytest.raises(ContractViolationError):
            fact_source_ids({"fact_id": "f9", "provenance": {}}, "document")

    def test_duplicate_actives_are_detected(self):
        facts = [_fact("med:lisinopril", "f1"), _fact("med:lisinopril", "f2")]
        assert duplicate_active_keys(facts) == ["med:lisinopril"]

    def test_delta_action_never_silently_overrides_review(self):
        assert set(DELTA_ACTION) == set(REVIEW_STATES)
        assert DELTA_ACTION["working_draft"] == "merge"
        assert DELTA_ACTION["open_review"] == "attach_delta_note"
        assert DELTA_ACTION["approved_pending_write"] == "open_new_review_item"
        assert DELTA_ACTION["persisted"] == "open_new_review_item"

    def test_safety_severities_match_engine_vocabulary(self):
        assert SAFETY_SEVERITIES == ("critical", "major", "moderate", "info")
        assert PUSH_ALERT_SEVERITIES <= set(SAFETY_SEVERITIES)

    def test_push_alert_card_threshold(self):
        assert renders_alert_card("critical")
        assert renders_alert_card("major")
        assert not renders_alert_card("moderate")
        assert not renders_alert_card("info")
        with pytest.raises(ValueError):
            renders_alert_card("severe")

    def test_lane_b_outputs_always_carry_push_safety(self):
        assert set(FactIdentity.__annotations__) == {
            "fact_id", "fact_key", "status", "superseded_by", "confidence",
        }
        assert {"type", "value", "provenance"} <= set(CandidateFact.__annotations__)
        assert set(FactProvenance.__annotations__) == {"evidence", "extractor", "prompt_version"}
        assert set(LaneBOutputs.__annotations__) == {
            "draft_version", "candidate_facts", "structured_record",
            "validation_report", "safety_alerts",
        }
        assert set(SafetyAlertCard.__annotations__) == {
            "alert_id", "session_id", "alert_type", "severity", "message",
            "fact_keys", "evidence",
        }
        assert SAFETY_ALERT_TYPES == ("allergy", "interaction", "contraindication")
        assert set(CompileJob.__annotations__) == {
            "session_id",
            "base_draft_version",
            "new_segment_ids",
            "new_doc_ids",
            "full_recompute",
        }


@pytest.mark.unit
class TestTaskGoldenSet:
    def test_well_formed(self):
        rows = _load("intent_task_v2.jsonl")
        ids = [r["id"] for r in rows]

        assert len(rows) >= 20
        assert len(ids) == len(set(ids))
        for r in rows:
            assert r["channel"] in EXPLICIT_CHANNELS, r["id"]
            assert r["expected_task_subtype"] in TASK_SUBTYPES, r["id"]
            assert r["expected_mode"] in INTERVENTION_MODES, r["id"]
            assert set(r.get("source_prefs", [])) <= set(SOURCE_KINDS), r["id"]
            assert r["expected_dispatch"] in DISPATCH_VALUES, r["id"]
            assert r["expected_dispatch_rule"] in range(1, 7), r["id"]
            assert isinstance(r.get("expected_sub_asks", []), list), r["id"]

    @pytest.mark.parametrize("row", _load("intent_task_v2.jsonl"), ids=lambda r: r["id"])
    def test_policy_matches_expected_mode(self, row):
        outcome = resolve_intervention(row["channel"], "copilot", row["expected_task_subtype"])
        assert outcome["mode"] == row["expected_mode"]

    def test_dispatch_values_are_valid(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            assert r["expected_dispatch"] in DISPATCH_VALUES, r["id"]

    @pytest.mark.parametrize("row", _load("intent_task_v2.jsonl"), ids=lambda r: r["id"])
    def test_dispatch_matches_expected(self, row):
        slots = {"sub_asks": row["expected_sub_asks"], "readings_conflict": row.get("readings_conflict", False)}
        decision = dispatch_assist(_context(channel=row["channel"]), slots)
        assert (decision["dispatch"], decision["dispatch_rule"]) == (
            row["expected_dispatch"], row["expected_dispatch_rule"]
        )

    def test_golden_set_covers_dispatch_rules_2_to_5(self):
        rows = _load("intent_task_v2.jsonl")
        # Rule 1 is ambient only; all golden rows are explicit.
        assert {2, 3, 4, 5} <= {r["expected_dispatch_rule"] for r in rows}
        assert "planning_agent" not in {r["expected_dispatch"] for r in rows}

    def test_workflow_rows_have_one_accepted_workflow(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            if r["expected_dispatch"] == "workflow":
                accepted_workflows = sum(
                    score >= SUB_ASK_MIN_CONFIDENCE
                    for sa in r["expected_sub_asks"]
                    for evidence_class, score in sa["class_scores"].items()
                    if evidence_class != "no_workflow"
                )
                assert accepted_workflows == 1, r["id"]

    def test_fanout_rows_have_multiple_independent_workflows(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            if r["expected_dispatch"] == "fanout":
                assert all(not sa["depends_on"] for sa in r["expected_sub_asks"]), r["id"]
                accepted_workflows = sum(
                    score >= SUB_ASK_MIN_CONFIDENCE
                    for sa in r["expected_sub_asks"]
                    for evidence_class, score in sa["class_scores"].items()
                    if evidence_class != "no_workflow"
                )
                assert 1 < accepted_workflows <= MAX_FANOUT_WORKFLOWS, r["id"]

    def test_rule_3_rows_have_depends_on_or_no_workflow(self):
        rows = _load("intent_task_v2.jsonl")
        pa_rows = [r for r in rows if r["expected_dispatch_rule"] == 3]
        assert len(pa_rows) >= 1
        for r in pa_rows:
            has_deps = any(sa["depends_on"] for sa in r["expected_sub_asks"])
            has_no_wf = any(
                sa["class_scores"].get("no_workflow", 0) >= SUB_ASK_MIN_CONFIDENCE
                for sa in r["expected_sub_asks"]
            )
            assert has_deps or has_no_wf, r["id"]


@pytest.mark.unit
class TestAddresseeGoldenSet:
    def test_well_formed(self):
        rows = _load("intent_addressee_v1.jsonl")
        ids = [r["id"] for r in rows]

        assert len(rows) >= 15
        assert len(ids) == len(set(ids))
        for r in rows:
            assert r["speaker"] in GATE_INPUT_SPEAKERS, r["id"]
            assert r["expected_addressee"] in ADDRESSEES, r["id"]
            assert ("task_subtype_if_copilot" in r) == (r["expected_addressee"] == "copilot"), r["id"]
            if r["speaker"] == "Patient":
                assert r["expected_addressee"] != "copilot", r["id"]

    def test_covers_patient_directed_hard_negatives(self):
        rows = _load("intent_addressee_v1.jsonl")
        patient_questions = [
            r["text"] for r in rows
            if r["expected_addressee"] == "patient" and r["text"].rstrip().endswith("?")
        ]
        assert len(patient_questions) >= 3
        assert "What was your last blood pressure reading?" in patient_questions

    @pytest.mark.parametrize("row", _load("intent_addressee_v1.jsonl"), ids=lambda r: r["id"])
    def test_every_ambient_row_is_silent_in_v1(self, row):
        outcome = resolve_intervention(
            "ambient_transcript", row["expected_addressee"], row.get("task_subtype_if_copilot")
        )
        assert outcome["mode"] == "silent"

    @pytest.mark.parametrize("row", _load("intent_addressee_v1.jsonl"), ids=lambda r: r["id"])
    def test_research_chips_only_on_copilot_rows(self, row):
        task = row.get("task_subtype_if_copilot")
        outcome = resolve_intervention(
            "ambient_transcript", row["expected_addressee"], task, ambient_research_enabled=True
        )
        # The addressee golden set has no Stage B dispatch. Without a fixed
        # workflow/fan-out result, ambient research remains silent.
        assert outcome["mode"] == "silent"


@pytest.mark.unit
@pytest.mark.skipif(not _CONTRACT_DOC.exists(), reason="docs/ not present (e.g. server-only image)")
class TestContractDocSync:
    def test_doc_names_version_and_every_enum_value(self):
        text = _CONTRACT_DOC.read_text()
        assert f"`{RUNTIME_CONTRACT_VERSION}`" in text
        values = (
            *ADDRESSEES,
            *CHANNELS,
            *TASK_SUBTYPES,
            *INTERVENTION_MODES,
            *LANES,
            *TOOL_IDS,
            *TOOL_CALLERS,
            *LANE_B_STAGES,
            *SOURCE_KINDS,
            *FACT_STATUSES,
            *REVIEW_STATES,
            *SAFETY_SEVERITIES,
            *EVIDENCE_STATES,
            *EVIDENCE_CLASSES,
            *DISPATCH_VALUES,
            *CLARIFY_KINDS,
            *PHYSICIAN_CHOICES,
            *OUTCOME_KINDS,
            *ANSWER_STATUSES,
            *INGEST_LEVELS,
            *REQUIREMENT_STATUSES,
            *FAILURE_CODES,
            NO_SOURCE_ERROR,
            NOT_COVERED_ERROR,
            "safety_alert_raised",
        )
        for value in values:
            assert re.search(rf"`{re.escape(value)}`", text), value

    def test_doc_provisional_numbers_match_code(self):
        text = _CONTRACT_DOC.read_text()
        for number in (
            AMBIENT_CHIP_MIN_CONFIDENCE,
            SUB_ASK_MIN_CONFIDENCE,
            MAX_FANOUT_WORKFLOWS,
            REFERENCE_RESOLUTION_WAIT_MS,
            RECHECK_INTERVAL_MS,
            POST_BARRIER_RESERVE_MS,
        ):
            assert f"`{number}`" in text, number

    def test_doc_has_no_superseded_v1_0_names(self):
        text = _CONTRACT_DOC.read_text()
        for stale in (
            "addressed_voice",
            "intent_golden_v1",
            "DEFAULT_RETRIEVAL_PLAN",
            "copilot_factoid",
            "retrieve_labs",   # retired in 1.2
            "safety_check",    # retired in 1.2
            "bounded_agent",   # renamed to planning_agent in 1.2
            "WorkflowState",   # replaced by PlanRequest
            "WorkerPlan",      # planner deferred (SDD §9.2)
            "TASK_EXECUTOR_MODE",
            "FIXED_TOOL_CHAINS",
            "QUERY_MATERIALIZATION_WAIT_MS",
            "EvidenceSpanRef",
            "supersedes_answer_id",
            "review_package",
            "new_document_ids",
            "supporting_fact_ids",
            "uploaded_doc",
            "prior_labs",
            "prior_docs",
            "prior_visits",
            "doctor_id",
        ):
            assert stale not in text, stale
