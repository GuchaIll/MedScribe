"""
Locks the copilot runtime contract (agent refactor Phase 1A, contract 1.2):
two-stage intent gate with sub-asks, dispatch table, executor types, shared
tool registry, Lane B outputs, and the golden sets.

If one of these fails, the contract changed. Follow change control in
docs/copilot_runtime_contract.md §10 instead of editing the expectation.
"""

import json
import re
from pathlib import Path

import pytest

from app.agents.compile_contracts import (
    DELTA_ACTION,
    FACT_STATUSES,
    PUSH_ALERT_SEVERITIES,
    REVIEW_STATES,
    SAFETY_SEVERITIES,
    CompileJob,
    LaneBOutputs,
    SafetyAlertCard,
    duplicate_active_keys,
    make_fact_key,
    renders_alert_card,
    supersede,
)
from app.agents.config import (
    MAX_FANOUT_WORKFLOWS,
    QUERY_MATERIALIZATION_WAIT_MS,
    SUB_ASK_MIN_CONFIDENCE,
)
from app.agents.intent.executor_contract import (
    AGENT_WALL_CLOCK_BUDGET_MS,
    CLARIFY_KINDS,
    DISPATCH_VALUES,
    EXECUTOR_MODES,
    FIXED_TOOL_CHAINS,
    MAX_AGENT_TOOL_CALLS,
    TASK_EXECUTOR_MODE,
    WORKFLOW_NAME,
    ClarifyRequest,
    PlanTask,
    ScopeChoice,
    WorkerPlan,
    WorkflowState,
    dispatch_assist,
    grounding_verdict,
    validate_agent_step,
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
    AGENT_ALLOWLIST,
    EVIDENCE_STATES,
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
    Citation,
    Claim,
    Derivation,
    ToolInvocationReceipt,
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
        "source_prefs": ["prior_labs"],
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


def _fact(fact_key, fact_id, status="active"):
    return {
        "fact_key": fact_key,
        "fact_id": fact_id,
        "status": status,
        "superseded_by": None,
        "source_segment_ids": [f"seg-{fact_id}"],
        "source_doc_ids": [],
        "confidence": 0.9,
    }


def _tool_result(**overrides):
    result = {
        "tool_id": "retrieve_structured",
        "ok": True,
        "data": {"analyte": "rbc", "value": 4.6, "unit": "10^6/uL"},
        "citations": [
            {
                "source_kind": "prior_labs",
                "source_id": "lab-123",
                "snippet": None,
                "observed_at": "2026-08-01",
                "received_at": "2026-08-01T08:00:00Z",
                "evidence_state": "materialized",
                "locator": None,
                "score": None,
            }
        ],
        "error": None,
        "receipt": {},
    }
    result.update(overrides)
    return result


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
            "general",
            "compile",
            "note",
            "doc_ingest",
            "session_control",
            "no_workflow",
        )

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

    def test_research_chip_needs_copilot_confidence_and_concrete_task(self):
        def ambient(addressee, task, confidence=0.9, router_ok=True):
            return resolve_intervention(
                "ambient_transcript",
                addressee,
                task,
                addressee_confidence=confidence,
                router_ok=router_ok,
                ambient_research_enabled=True,
            )["mode"]

        assert ambient("copilot", "factoid") == "suggest_chip"
        assert ambient("copilot", "factoid", confidence=0.5) == "silent"
        assert ambient("patient", "factoid") == "silent"
        assert ambient("unknown", "factoid") == "silent"
        assert ambient("copilot", "session_control") == "silent"
        assert ambient("copilot", "unknown") == "silent"
        assert ambient("copilot", "factoid", router_ok=False) == "silent"

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
        assert FIXED_TOOL_CHAINS["factoid"]

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
    def test_executor_modes_are_frozen(self):
        assert EXECUTOR_MODES == ("fixed", "planning_agent")

    def test_every_task_has_an_executor_mode(self):
        assert set(TASK_EXECUTOR_MODE) == set(TASK_SUBTYPES)
        assert set(TASK_EXECUTOR_MODE.values()) <= set(EXECUTOR_MODES)

    def test_all_tasks_are_fixed_in_1_2(self):
        # trajectory and compare were bounded_agent in 1.1; they are fixed workflows in 1.2.
        assert all(mode == "fixed" for mode in TASK_EXECUTOR_MODE.values())

    def test_fixed_chains_cover_every_task_with_assist_tools(self):
        assert set(FIXED_TOOL_CHAINS) == set(TASK_SUBTYPES)
        for task, chain in FIXED_TOOL_CHAINS.items():
            for tool_id in chain:
                assert TOOL_SPECS[tool_id]["assist_callable"], (task, tool_id)

    def test_factoid_chain_uses_retrieve_structured_not_labs(self):
        chain = FIXED_TOOL_CHAINS["factoid"]
        assert "retrieve_structured" in chain
        assert "retrieve_labs" not in chain
        assert chain[-1] == "retrieve_docs"

    def test_safety_chain_uses_split_tools(self):
        chain = FIXED_TOOL_CHAINS["safety"]
        assert "check_med_conflicts" in chain
        assert "check_dosage" in chain
        assert "check_metric_alerts" in chain
        assert "safety_check" not in chain

    def test_trajectory_and_compare_chains_include_source_chunks(self):
        assert "retrieve_source_chunks" in FIXED_TOOL_CHAINS["trajectory"]
        assert "retrieve_source_chunks" in FIXED_TOOL_CHAINS["compare"]

    def test_dispatch_values_are_frozen(self):
        assert set(DISPATCH_VALUES) == {"silent", "clarify", "workflow", "fanout", "planning_agent"}

    def test_clarify_kinds_are_frozen(self):
        assert set(CLARIFY_KINDS) == {"scope", "reading", "rephrase", "narrow"}

    def test_provisional_constants_from_config(self):
        assert SUB_ASK_MIN_CONFIDENCE == 0.75
        assert MAX_FANOUT_WORKFLOWS == 3
        assert QUERY_MATERIALIZATION_WAIT_MS == 20_000

    def test_planner_budget_carried_from_1_1(self):
        assert MAX_AGENT_TOOL_CALLS == 6
        assert AGENT_WALL_CLOCK_BUDGET_MS == 8000

    def test_clarify_request_shape(self):
        assert set(ClarifyRequest.__annotations__) == {"kind", "choices", "allow_free_text"}

    def test_scope_choice_shape(self):
        assert set(ScopeChoice.__annotations__) == {
            "scope_id", "rank", "label", "supporting_fact_ids", "expands_to"
        }

    def test_worker_plan_shape(self):
        assert set(WorkerPlan.__annotations__) == {
            "plan_id", "tasks", "synthesis_goal", "needs_scope"
        }
        assert set(PlanTask.__annotations__) == {
            "task_id", "tool_id", "args", "depends_on", "sub_ask_id"
        }

    def test_workflow_state_shape(self):
        assert set(WorkflowState.__annotations__) == {
            "workflow_id", "reason", "goal", "scope",
            "required_evidence", "remaining_requirements",
            "acquired", "sources_checked",
            "as_of_receipt", "latency_remaining_ms",
        }

    def test_valid_planner_step_runs(self):
        step = {"tool_id": "retrieve_structured", "args": {"kind": "lab_result", "analyte": "rbc"}}
        assert validate_agent_step(step, calls_made=0, elapsed_ms=0) == []

    @pytest.mark.parametrize(
        "step, calls_made, elapsed_ms, fragment",
        [
            ({"tool_id": "generate_note", "args": {}}, 0, 0, "allowlist"),
            ({"tool_id": "check_med_conflicts", "args": {}}, 0, 0, "allowlist"),
            ({"tool_id": "retrieve_for_candidates", "args": {}}, 0, 0, "allowlist"),
            ({"tool_id": "retrieve_structured", "args": {"patient_id": "p1"}}, 0, 0, "scope keys"),
            ({"tool_id": "retrieve_docs", "args": {"filters": {"tenant_id": "t1"}}}, 0, 0, "filters.tenant_id"),
            ({"tool_id": "retrieve_everything", "args": {}}, 0, 0, "unknown tool"),
            ({"tool_id": "retrieve_structured", "args": []}, 0, 0, "args must be an object"),
            ({"tool_id": "retrieve_structured", "args": {}}, MAX_AGENT_TOOL_CALLS, 0, "call cap"),
            ({"tool_id": "retrieve_structured", "args": {}}, 0, AGENT_WALL_CLOCK_BUDGET_MS, "wall-clock"),
        ],
    )
    def test_invalid_planner_step_is_refused(self, step, calls_made, elapsed_ms, fragment):
        errors = validate_agent_step(step, calls_made=calls_made, elapsed_ms=elapsed_ms)
        assert any(fragment in e for e in errors), errors

    def test_any_unsupported_claim_blocks_rendering(self):
        assert grounding_verdict([]) == "render"
        assert grounding_verdict(["claim-2"]) == "refuse"


@pytest.mark.unit
class TestDispatchAssist:
    """dispatch_assist() is a pure function; all branches tested directly."""

    def _slots_with(self, sub_asks=None, readings_conflict=False):
        return {
            "sub_asks": sub_asks or [],
            "readings_conflict": readings_conflict,
        }

    def test_ambient_is_always_silent(self):
        for sub_asks in ([], [_sub_ask()]):
            assert dispatch_assist("ambient_transcript", self._slots_with(sub_asks)) == "silent"

    def test_no_sub_asks_triggers_clarify(self):
        assert dispatch_assist("explicit_ui", self._slots_with([])) == "clarify"

    def test_no_accepted_class_triggers_clarify(self):
        sa = _sub_ask(class_scores={"measurement": 0.50})  # below threshold
        assert dispatch_assist("explicit_ui", self._slots_with([sa])) == "clarify"

    def test_underspecified_triggers_clarify(self):
        sa = _sub_ask(entity_hints=[], domain_hints=[], class_scores={"session": 0.90})
        assert dispatch_assist("explicit_ui", self._slots_with([sa])) == "clarify"

    def test_readings_conflict_triggers_clarify(self):
        sa = _sub_ask(class_scores={"measurement": 0.92})
        assert dispatch_assist("explicit_ui", self._slots_with([sa], readings_conflict=True)) == "clarify"

    def test_depends_on_triggers_planning_agent(self):
        sa = _sub_ask(class_scores={"measurement": 0.92}, depends_on=["sa-0"])
        assert dispatch_assist("explicit_ui", self._slots_with([sa])) == "planning_agent"

    def test_no_workflow_class_triggers_planning_agent(self):
        sa = _sub_ask(class_scores={"no_workflow": 0.85})
        assert dispatch_assist("explicit_ui", self._slots_with([sa])) == "planning_agent"

    def test_one_independent_sub_ask_triggers_workflow(self):
        sa = _sub_ask(class_scores={"measurement": 0.92})
        assert dispatch_assist("explicit_ui", self._slots_with([sa])) == "workflow"

    def test_two_independent_sub_asks_triggers_fanout(self):
        sa1 = _sub_ask(sub_ask_id="sa-1", entity_hints=["rbc"], class_scores={"measurement": 0.92})
        sa2 = _sub_ask(sub_ask_id="sa-2", entity_hints=["sodium"], class_scores={"measurement": 0.88})
        assert dispatch_assist("explicit_ui", self._slots_with([sa1, sa2])) == "fanout"

    def test_over_max_fanout_triggers_clarify(self):
        sub_asks = [
            _sub_ask(sub_ask_id=f"sa-{i}", entity_hints=[f"lab-{i}"], class_scores={"measurement": 0.90})
            for i in range(MAX_FANOUT_WORKFLOWS + 1)
        ]
        assert dispatch_assist("explicit_ui", self._slots_with(sub_asks)) == "clarify"

    def test_exactly_max_fanout_triggers_fanout(self):
        sub_asks = [
            _sub_ask(sub_ask_id=f"sa-{i}", entity_hints=[f"lab-{i}"], class_scores={"measurement": 0.90})
            for i in range(MAX_FANOUT_WORKFLOWS)
        ]
        assert dispatch_assist("explicit_ui", self._slots_with(sub_asks)) == "fanout"

    def test_wake_word_follows_same_rules(self):
        sa = _sub_ask(class_scores={"measurement": 0.92})
        assert dispatch_assist("wake_word", self._slots_with([sa])) == "workflow"
        assert dispatch_assist("wake_word", self._slots_with([])) == "clarify"


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

    def test_planner_allowlist_equals_agent_allowlist_alias(self):
        assert PLANNER_ALLOWLIST == AGENT_ALLOWLIST

    def test_planner_allowlist_is_read_and_scratch_only(self):
        assert all(TOOL_SPECS[t]["writes"] in ("none", "session_scratch") for t in PLANNER_ALLOWLIST)

    def test_note_generation_is_neither_a_compile_stage_nor_planner_tool(self):
        spec = TOOL_SPECS["generate_note"]
        assert spec["lane_b_stages"] == ()
        assert spec["assist_callable"]
        assert not spec["planner_allowlisted"]

    def test_scope_is_injected_never_model_supplied(self):
        assert {"patient_id", "tenant_id"} <= SCOPE_ARG_KEYS
        errors = validate_model_tool_args("retrieve_structured", {"items": [{"patient_id": "p1"}]})
        assert any("items[0].patient_id" in e for e in errors), errors
        assert validate_model_tool_args("retrieve_structured", {"kind": "lab_result", "analyte": "rbc"}) == []

    def test_evidence_state_values_are_frozen(self):
        assert EVIDENCE_STATES == ("received", "materialized", "validated", "authorized")

    def test_citation_shape_includes_1_2_fields(self):
        fields = set(Citation.__annotations__)
        assert "received_at" in fields
        assert "evidence_state" in fields
        assert "locator" in fields

    def test_claim_and_derivation_shapes(self):
        assert set(Claim.__annotations__) == {"claim_id", "text", "citation_ids", "derivation"}
        assert set(Derivation.__annotations__) == {"operation", "input_citation_ids", "receipt_id"}

    def test_not_covered_error_is_defined(self):
        assert NOT_COVERED_ERROR == "not_covered"

    def test_grounded_result_passes(self):
        assert validate_tool_result(_tool_result()) == []

    def test_no_source_miss_is_valid(self):
        miss = _tool_result(tool_id="retrieve_structured", ok=False, data={}, citations=[], error=NO_SOURCE_ERROR)
        assert validate_tool_result(miss) == []

    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"citations": []}, "ungrounded"),
            ({"tool_id": "compare_findings", "citations": []}, "ungrounded"),
            ({"citations": [{"source_kind": "web", "source_id": "x"}]}, "known source_kind"),
            ({"citations": [{"source_kind": "prior_labs", "source_id": ""}]}, "source_id"),
            ({"ok": False, "error": None}, "error string"),
            ({"tool_id": "retrieve_everything"}, "unknown tool"),
        ],
    )
    def test_invalid_tool_result_is_rejected(self, overrides, fragment):
        errors = validate_tool_result(_tool_result(**overrides))
        assert any(fragment in e for e in errors), errors

    def test_safety_tools_may_return_without_citations(self):
        for tool_id in ("check_med_conflicts", "check_dosage", "check_metric_alerts"):
            result = _tool_result(tool_id=tool_id, citations=[], data={"alerts": []})
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
class TestLaneBContracts:
    def test_fact_statuses_and_review_states_are_frozen(self):
        assert FACT_STATUSES == ("active", "superseded", "retracted", "needs_review")
        assert REVIEW_STATES == ("working_draft", "open_review", "approved_pending_write", "persisted")

    def test_make_fact_key_normalizes(self):
        assert make_fact_key("allergy", "Amoxicillin") == "allergy:amoxicillin"
        assert make_fact_key("lab", "RBC", "2024-11-02") == "lab:rbc:2024-11-02"
        assert make_fact_key("vital", "Blood Pressure") == "vital:blood_pressure"

    @pytest.mark.parametrize("args", [("allergy", ""), ("", "amoxicillin"), ("allergy", "  ")])
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
        assert superseded["source_segment_ids"] == prior["source_segment_ids"]

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
        assert "safety_alerts" in LaneBOutputs.__annotations__
        assert {"severity", "fact_keys", "evidence", "session_id"} <= set(SafetyAlertCard.__annotations__)
        assert set(CompileJob.__annotations__) == {
            "session_id",
            "base_draft_version",
            "new_segment_ids",
            "new_document_ids",
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
            assert isinstance(r.get("expected_sub_asks", []), list), r["id"]

    @pytest.mark.parametrize("row", _load("intent_task_v2.jsonl"), ids=lambda r: r["id"])
    def test_policy_matches_expected_mode(self, row):
        outcome = resolve_intervention(row["channel"], "copilot", row["expected_task_subtype"])
        assert outcome["mode"] == row["expected_mode"]

    def test_dispatch_values_are_valid(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            assert r["expected_dispatch"] in DISPATCH_VALUES, r["id"]

    def test_golden_set_covers_all_dispatch_values_except_silent(self):
        rows = _load("intent_task_v2.jsonl")
        dispatches = {r["expected_dispatch"] for r in rows}
        # silent is only for ambient_transcript; all golden rows are explicit
        assert {"clarify", "workflow", "fanout", "planning_agent"} <= dispatches

    def test_workflow_rows_have_one_accepted_sub_ask(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            if r["expected_dispatch"] == "workflow":
                accepted = [
                    sa for sa in r["expected_sub_asks"]
                    if any(v >= SUB_ASK_MIN_CONFIDENCE for v in sa["class_scores"].values())
                ]
                assert len(accepted) == 1, r["id"]

    def test_fanout_rows_have_multiple_independent_sub_asks(self):
        rows = _load("intent_task_v2.jsonl")
        for r in rows:
            if r["expected_dispatch"] == "fanout":
                independent = [sa for sa in r["expected_sub_asks"] if not sa["depends_on"]]
                assert len(independent) >= 2, r["id"]

    def test_planning_agent_rows_have_depends_on_or_no_workflow(self):
        rows = _load("intent_task_v2.jsonl")
        pa_rows = [r for r in rows if r["expected_dispatch"] == "planning_agent"]
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
        expect_chip = row["expected_addressee"] == "copilot" and task not in ("unknown", "session_control")
        assert (outcome["mode"] == "suggest_chip") == expect_chip


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
            *EXECUTOR_MODES,
            *TOOL_IDS,
            *TOOL_CALLERS,
            *LANE_B_STAGES,
            *SOURCE_KINDS,
            *FACT_STATUSES,
            *REVIEW_STATES,
            *SAFETY_SEVERITIES,
            *EVIDENCE_STATES,
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
            MAX_AGENT_TOOL_CALLS,
            AGENT_WALL_CLOCK_BUDGET_MS,
            SUB_ASK_MIN_CONFIDENCE,
            MAX_FANOUT_WORKFLOWS,
            QUERY_MATERIALIZATION_WAIT_MS,
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
        ):
            assert stale not in text, stale
