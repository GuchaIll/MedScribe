"""
Intent gate contract — frozen v1 (agent refactor Phase 0).

Two stages with different error costs:

- Stage A — addressee: is the speaker talking to the patient or to MedScribe?
  Errors here are safety-critical (false barge-in). Explicit channels
  short-circuit to "copilot"; ambient transcript skips the gate in v1.
- Stage B — task subtype + slots on copilot-directed input. Errors here are
  recoverable (the clinician re-asks).

The gate never emits a tool plan; the executor owns plans
(app.agents.intent.executor_contract). Types only — semantics and change
control live in docs/copilot_runtime_contract.md.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, get_args

from app.agents.tool_contracts import (
    RUNTIME_CONTRACT_VERSION,
    SCOPE_ARG_KEYS,
    SOURCE_KINDS,
    SourceKind,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

Addressee = Literal["patient", "copilot", "unknown"]

# Where the input came from, not what it means
Channel = Literal["explicit_ui", "wake_word", "ambient_transcript"]

TaskSubtype = Literal[
    # Assist answers
    "factoid",
    "trajectory",
    "compare",
    "safety",
    # Jobs
    "compile",
    "note",
    "doc_ingest",
    "session_control",
    # Fallback
    "unknown",
]

# Plan letters: A = live_stream, A-assist = assist, B = compile, C = durability
Lane = Literal["live_stream", "assist", "compile", "note_job", "doc_ingest", "durability"]

Urgency = Literal["silent", "background", "interactive"]
SpeakPolicy = Literal["none", "text_only", "text_and_tts"]

# What the clinician sees. "alert" comes from Lane B push safety, never from the gate.
InterventionMode = Literal["silent", "suggest_chip", "answer", "job", "clarify", "alert"]

DecisionSource = Literal["explicit_channel", "heuristics", "router_model", "fallback"]

EncounterStatus = Literal[
    "listening",
    "transcript_appended",
    "intent_detected",
    "assist_answering",
    "assist_answered",
    "compile_running",
    "draft_ready",
    "note_running",
    "note_ready",
    "safety_alert_raised",
    "review_pending",
    "review_approved",
    "session_finalizing",
    "persisted",
]

ADDRESSEES: Tuple[str, ...] = get_args(Addressee)
CHANNELS: Tuple[str, ...] = get_args(Channel)
TASK_SUBTYPES: Tuple[str, ...] = get_args(TaskSubtype)
LANES: Tuple[str, ...] = get_args(Lane)
URGENCIES: Tuple[str, ...] = get_args(Urgency)
SPEAK_POLICIES: Tuple[str, ...] = get_args(SpeakPolicy)
INTERVENTION_MODES: Tuple[str, ...] = get_args(InterventionMode)
DECISION_SOURCES: Tuple[str, ...] = get_args(DecisionSource)
ENCOUNTER_STATUSES: Tuple[str, ...] = get_args(EncounterStatus)

# Channels that imply addressee="copilot" without a Stage A decision
EXPLICIT_CHANNELS: FrozenSet[str] = frozenset({"explicit_ui", "wake_word"})

ASSIST_TASKS: FrozenSet[str] = frozenset({"factoid", "trajectory", "compare", "safety"})
JOB_TASKS: FrozenSet[str] = frozenset({"compile", "note", "doc_ingest", "session_control"})

TASK_LANE: Dict[str, str] = {
    "factoid": "assist",
    "trajectory": "assist",
    "compare": "assist",
    "safety": "assist",
    "compile": "compile",
    "note": "note_job",
    "doc_ingest": "doc_ingest",
    "session_control": "durability",
    "unknown": "assist",
}

# Transcript speakers the gate accepts. "Scribe" rows are MedScribe's own
# output and must never be routed back in as input.
GATE_INPUT_SPEAKERS: Tuple[str, ...] = ("Clinician", "Patient")

# Keys the gate must never emit: plans belong to the executor, scope to the runtime.
FORBIDDEN_DECISION_KEYS: FrozenSet[str] = frozenset({"plan", "tool_ids", "tool_args"}) | SCOPE_ARG_KEYS


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

class AddresseeDecision(TypedDict):
    addressee: Addressee
    confidence: float               # 0..1; 1.0 on explicit channels
    channel: Channel
    reason_codes: List[str]         # snake_case audit codes, never model reasoning text


class TaskSlots(TypedDict):
    task_subtype: TaskSubtype
    query_rewrite: Optional[str]    # normalized retrieval question
    time_range: Optional[str]       # e.g. "last_2_years"
    domain_hints: List[str]         # e.g. ["hematology"]
    source_prefs: List[SourceKind]  # hints only, not an executable plan
    entity_hints: List[str]         # e.g. ["rbc", "amoxicillin"]
    speak_policy: SpeakPolicy


class IntentDecision(TypedDict):
    """Composite audit object after Stage A (if any) + Stage B. No plan field."""
    addressee: AddresseeDecision
    task: Optional[TaskSlots]       # null unless addressee == "copilot"
    intervene: bool                 # produce user-visible copilot output now
    urgency: Urgency


class IntentDecisionEvent(TypedDict):
    """Audit envelope for the internal ``intent.decision`` event."""
    contract_version: str
    event_id: str
    session_id: str
    source: DecisionSource
    speaker: Optional[str]          # "Clinician" | "Patient" | None for UI input
    segment_ref: Optional[str]      # transcript segment / UI message id — no raw utterance text
    decision: IntentDecision
    mode: InterventionMode
    latency_ms: Optional[float]
    created_at: str                 # ISO-8601


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_unit_interval(value: Any) -> bool:
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return is_number and 0.0 <= value <= 1.0


def validate_intent_decision(decision: Dict[str, Any]) -> List[str]:
    """Return contract violations for a candidate IntentDecision (empty list = valid).

    Intended for checking gate output before the executor trusts it.
    """
    missing = set(IntentDecision.__annotations__) - set(decision)
    if missing:
        return [f"missing fields: {sorted(missing)}"]

    return [
        *_forbidden_key_errors(decision),
        *_addressee_errors(decision["addressee"]),
        *_task_errors(decision),
        *_cross_field_errors(decision),
    ]


def _forbidden_key_errors(decision: Dict[str, Any]) -> List[str]:
    found = set(decision) & FORBIDDEN_DECISION_KEYS
    if isinstance(decision["task"], dict):
        found |= set(decision["task"]) & FORBIDDEN_DECISION_KEYS
    return [f"gate must not emit {sorted(found)}"] if found else []


def _addressee_errors(addressee: Any) -> List[str]:
    if not isinstance(addressee, dict) or set(AddresseeDecision.__annotations__) - set(addressee):
        return ["addressee must be an AddresseeDecision"]

    errors: List[str] = []
    if addressee["addressee"] not in ADDRESSEES:
        errors.append(f"addressee={addressee['addressee']!r} not in contract")
    if addressee["channel"] not in CHANNELS:
        errors.append(f"channel={addressee['channel']!r} not in contract")
    if not _is_unit_interval(addressee["confidence"]):
        errors.append("addressee.confidence must be a number in [0, 1]")
    if not _is_str_list(addressee["reason_codes"]):
        errors.append("addressee.reason_codes must be a list of strings")
    if addressee["channel"] in EXPLICIT_CHANNELS and addressee["addressee"] != "copilot":
        errors.append("explicit channels imply addressee='copilot'")
    return errors


def _task_errors(decision: Dict[str, Any]) -> List[str]:
    addressee, task = decision["addressee"], decision["task"]
    is_copilot = isinstance(addressee, dict) and addressee.get("addressee") == "copilot"

    if not is_copilot:
        return [] if task is None else ["task must be null unless addressee is 'copilot'"]
    if not isinstance(task, dict) or set(TaskSlots.__annotations__) - set(task):
        return ["copilot-directed decisions need TaskSlots"]
    return _slot_errors(task)


def _slot_errors(task: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if task["task_subtype"] not in TASK_SUBTYPES:
        errors.append(f"task_subtype={task['task_subtype']!r} not in contract")
    if task["speak_policy"] not in SPEAK_POLICIES:
        errors.append(f"speak_policy={task['speak_policy']!r} not in contract")

    for name in ("domain_hints", "source_prefs", "entity_hints"):
        if not _is_str_list(task[name]):
            errors.append(f"{name} must be a list of strings")
    for name in ("query_rewrite", "time_range"):
        if task[name] is not None and not isinstance(task[name], str):
            errors.append(f"{name} must be a string or null")

    if _is_str_list(task["source_prefs"]):
        unknown = [s for s in task["source_prefs"] if s not in SOURCE_KINDS]
        if unknown:
            errors.append(f"source_prefs not in contract: {unknown}")
    return errors


def _cross_field_errors(decision: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    intervene, urgency, task = decision["intervene"], decision["urgency"], decision["task"]

    if urgency not in URGENCIES:
        errors.append(f"urgency={urgency!r} not in contract")
    if not isinstance(intervene, bool):
        errors.append("intervene must be bool")
        return errors

    if intervene and urgency == "silent":
        errors.append("intervene=true cannot have urgency='silent'")
    if not intervene and urgency == "interactive":
        errors.append("intervene=false cannot have urgency='interactive'")
    if intervene and task is None:
        errors.append("intervene=true requires copilot task slots")
    if not intervene and isinstance(task, dict) and task.get("speak_policy") == "text_and_tts":
        errors.append("intervene=false cannot use text_and_tts")
    return errors
