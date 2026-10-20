"""
Intervention policy for the intent gate — v1.2 (Phase 1A, #50).

resolve_intervention() maps (channel, addressee, task) to the intervention
mode and urgency that the executor should use. This is the only place that
codifies the dispatch rules; tests lock the output.

AMBIENT_CHIP_MIN_CONFIDENCE: calibrated threshold for research-chip suggestions
on the ambient channel when ambient_research_enabled is True (§12.2).
Provisional — will migrate to config.py when backed by eval evidence.

Semantics: docs/copilot_runtime_contract.md §2, §12.1–12.2.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.intent.schemas import (
    ADDRESSEES,
    ASSIST_TASKS,
    CHANNELS,
    EXPLICIT_CHANNELS,
    JOB_TASKS,
    TASK_SUBTYPES,
)

# Provisional — §10 change control; listed in the contract doc as `0.6`.
AMBIENT_CHIP_MIN_CONFIDENCE: float = 0.6


def resolve_intervention(
    channel: str,
    addressee: str,
    task: Optional[str],
    *,
    addressee_confidence: float = 1.0,
    ambient_research_enabled: bool = False,
    router_ok: bool = True,
    tts_enabled: bool = False,
    dispatch: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the intervention decision for a gate output.

    Args:
        channel: one of CHANNELS.
        addressee: one of ADDRESSEES.
        task: one of TASK_SUBTYPES, or None if the gate could not classify.
        addressee_confidence: calibrated confidence from Stage A (0..1).
        ambient_research_enabled: whether the background research chip is on.
        router_ok: False when the routing model failed or timed out.
        tts_enabled: whether voice output is available in this session.
        dispatch: Stage B execution decision. Ambient research chips are only
            eligible for fixed `workflow` or `fanout` dispatches.

    Returns:
        Dict with keys: mode, intervene, urgency, speak_policy, reason_codes.

    Raises:
        ValueError: for unknown enum values or policy violations.
    """
    if channel not in CHANNELS:
        raise ValueError(f"channel={channel!r} not in CHANNELS")
    if addressee not in ADDRESSEES:
        raise ValueError(f"addressee={addressee!r} not in ADDRESSEES")
    if task is not None and task not in TASK_SUBTYPES:
        raise ValueError(f"task={task!r} not in TASK_SUBTYPES")
    if channel in EXPLICIT_CHANNELS and addressee != "copilot":
        raise ValueError(
            f"explicit channel {channel!r} requires addressee='copilot', got {addressee!r}"
        )

    if channel == "ambient_transcript":
        return _ambient(
            addressee, task, addressee_confidence, ambient_research_enabled,
            router_ok, dispatch,
        )
    return _explicit(channel, task, router_ok, tts_enabled)


def _ambient(
    addressee: str,
    task: Optional[str],
    confidence: float,
    research_enabled: bool,
    router_ok: bool,
    dispatch: Optional[str],
) -> Dict[str, Any]:
    chip_eligible = (
        research_enabled
        and addressee == "copilot"
        and task is not None
        and task not in ("unknown", "session_control")
        and dispatch in ("workflow", "fanout")
        and confidence >= AMBIENT_CHIP_MIN_CONFIDENCE
        and router_ok
    )
    if chip_eligible:
        return {
            "mode": "suggest_chip",
            "intervene": False,
            "urgency": "background",
            "speak_policy": "text_only",
            "reason_codes": ["ambient_chip"],
        }
    return {
        "mode": "silent",
        "intervene": False,
        "urgency": "silent",
        "speak_policy": "none",
        "reason_codes": ["ambient_v1_silent"],
    }


def _explicit(channel: str, task: Optional[str], router_ok: bool, tts_enabled: bool) -> Dict[str, Any]:
    speak_answer = "text_and_tts" if tts_enabled else "text_only"

    # Gate failure with no task -> fall back to factoid chain (§12.1 fallback rule).
    if task is None and not router_ok:
        return {
            "mode": "answer",
            "intervene": True,
            "urgency": "interactive",
            "speak_policy": speak_answer,
            "reason_codes": ["default_factoid_chain"],
        }

    # Unknown or unclassified -> clarify.
    if task is None or task == "unknown":
        return {
            "mode": "clarify",
            "intervene": True,
            "urgency": "interactive",
            "speak_policy": "text_only",
            "reason_codes": ["unknown_task"],
        }

    # Voice never executes session control directly (§12.1).
    if channel == "wake_word" and task == "session_control":
        return {
            "mode": "suggest_chip",
            "intervene": False,
            "urgency": "background",
            "speak_policy": "text_only",
            "reason_codes": ["voice_session_control"],
        }

    if task in ASSIST_TASKS:
        return {
            "mode": "answer",
            "intervene": True,
            "urgency": "interactive",
            "speak_policy": speak_answer,
            "reason_codes": ["assist_task"],
        }

    if task in JOB_TASKS:
        return {
            "mode": "job",
            "intervene": True,
            "urgency": "interactive",
            "speak_policy": "text_only",
            "reason_codes": ["job_task"],
        }

    return {
        "mode": "clarify",
        "intervene": True,
        "urgency": "interactive",
        "speak_policy": "text_only",
        "reason_codes": ["unclassified"],
    }
