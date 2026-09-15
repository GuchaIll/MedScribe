"""
Intervention policy — frozen v1 (agent refactor Phase 0).

Pure function: (channel, addressee, task subtype) -> what the clinician sees.
Encodes docs/copilot_runtime_contract.md §4:

- v1 copilot channels are explicit only: copilot input box and wake word
- ambient transcript is always silent in v1; suggestion chips exist only
  behind a research flag, and ambient never auto-answers
- explicit channels always get a visible response
- voice never ends or signs off a session; it can only offer a confirm chip
- gate failure: explicit channels fall back to the factoid chain, ambient stays silent

Lane B push safety alerts do not pass through here; they always render as
"alert" cards. The rule structure is frozen; the chip threshold is provisional.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, TypedDict

from app.agents.intent.schemas import (
    ADDRESSEES,
    ASSIST_TASKS,
    CHANNELS,
    EXPLICIT_CHANNELS,
    JOB_TASKS,
    TASK_SUBTYPES,
    InterventionMode,
    SpeakPolicy,
    Urgency,
)

# Research-only: minimum Stage A addressee confidence before an ambient chip.
AMBIENT_CHIP_MIN_CONFIDENCE = 0.6

_INTERVENING_MODES = frozenset({"answer", "job", "clarify", "alert"})


class InterventionOutcome(TypedDict):
    mode: InterventionMode
    intervene: bool
    urgency: Urgency
    speak_policy: SpeakPolicy
    reason_codes: List[str]


def _outcome(mode: str, reasons: Sequence[str], *, tts_enabled: bool = False) -> InterventionOutcome:
    if mode == "silent":
        urgency, speak = "silent", "none"
    elif mode == "suggest_chip":
        urgency, speak = "background", "text_only"
    else:
        urgency = "interactive"
        speak = "text_and_tts" if tts_enabled and mode == "answer" else "text_only"
    return InterventionOutcome(
        mode=mode,
        intervene=mode in _INTERVENING_MODES,
        urgency=urgency,
        speak_policy=speak,
        reason_codes=list(reasons),
    )


def resolve_intervention(
    channel: str,
    addressee: str,
    task_subtype: Optional[str],
    *,
    addressee_confidence: float = 1.0,
    router_ok: bool = True,
    ambient_research_enabled: bool = False,
    tts_enabled: bool = False,
) -> InterventionOutcome:
    """Decide whether MedScribe responds, and how.

    ``router_ok=False`` means the gate timed out, errored, or produced output
    that failed validation; ``task_subtype`` is then ignored.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if addressee not in ADDRESSEES:
        raise ValueError(f"unknown addressee {addressee!r}")
    if task_subtype is not None and task_subtype not in TASK_SUBTYPES:
        raise ValueError(f"unknown task_subtype {task_subtype!r}")
    if channel in EXPLICIT_CHANNELS and addressee != "copilot":
        raise ValueError("explicit channels imply addressee='copilot'")

    if channel in EXPLICIT_CHANNELS:
        return _resolve_explicit(channel, task_subtype, router_ok, tts_enabled)
    return _resolve_ambient(
        addressee, task_subtype, addressee_confidence, router_ok, ambient_research_enabled
    )


def _resolve_explicit(
    channel: str,
    task_subtype: Optional[str],
    router_ok: bool,
    tts_enabled: bool,
) -> InterventionOutcome:
    # The clinician addressed MedScribe on purpose: never silent.
    reasons = [channel]
    if not router_ok:
        return _outcome("answer", reasons + ["router_unavailable", "default_factoid_chain"], tts_enabled=tts_enabled)
    if task_subtype in ASSIST_TASKS:
        return _outcome("answer", reasons + ["copilot_question"], tts_enabled=tts_enabled)
    if task_subtype == "session_control" and channel == "wake_word":
        return _outcome("suggest_chip", reasons + ["session_control_requires_confirmation"])
    if task_subtype in JOB_TASKS:
        return _outcome("job", reasons + ["job_request"])
    return _outcome("clarify", reasons + ["task_unclear"])


def _resolve_ambient(
    addressee: str,
    task_subtype: Optional[str],
    addressee_confidence: float,
    router_ok: bool,
    ambient_research_enabled: bool,
) -> InterventionOutcome:
    reasons = ["ambient_transcript"]
    if not ambient_research_enabled:
        return _outcome("silent", reasons + ["ambient_v1_silent"])
    if not router_ok:
        return _outcome("silent", reasons + ["router_unavailable"])
    if addressee != "copilot":
        return _outcome("silent", reasons + ["not_copilot_directed"])
    if addressee_confidence < AMBIENT_CHIP_MIN_CONFIDENCE:
        return _outcome("silent", reasons + ["below_chip_threshold"])
    if task_subtype in (None, "unknown", "session_control"):
        return _outcome("silent", reasons + ["no_chip_for_task"])
    return _outcome("suggest_chip", reasons + ["research_chip"])
