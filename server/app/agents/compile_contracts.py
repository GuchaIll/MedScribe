"""
Lane B compile contracts — v1.2 (Phase 1A, #50).

Defines the fact-lifecycle types and helpers used by the compile pipeline
(Lane B): fact keys, status transitions, review state, delta-action table,
safety push alerts, and the compile job envelope.

Semantics and change control: docs/copilot_runtime_contract.md §7.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, get_args


# ---------------------------------------------------------------------------
# Fact lifecycle (§7.1)
# ---------------------------------------------------------------------------

FactStatus = Literal["active", "superseded", "retracted", "needs_review"]
FACT_STATUSES: Tuple[str, ...] = get_args(FactStatus)

ReviewState = Literal["working_draft", "open_review", "approved_pending_write", "persisted"]
REVIEW_STATES: Tuple[str, ...] = get_args(ReviewState)

# What the compile pipeline does when a new delta arrives in each review state.
# Never silently overwrites; always preserves the review chain.
DELTA_ACTION: Dict[str, str] = {
    "working_draft": "merge",
    "open_review": "attach_delta_note",
    "approved_pending_write": "open_new_review_item",
    "persisted": "open_new_review_item",
}

# ---------------------------------------------------------------------------
# Safety push (§7.4)
# ---------------------------------------------------------------------------

SafetySeverity = Literal["critical", "major", "moderate", "info"]
SAFETY_SEVERITIES: Tuple[str, ...] = get_args(SafetySeverity)

# Severities that produce a visible push alert card in the UI.
PUSH_ALERT_SEVERITIES: FrozenSet[str] = frozenset({"critical", "major"})


def renders_alert_card(severity: str) -> bool:
    """Return True when this severity produces a visible push alert card.

    Raises:
        ValueError: for unknown severity strings.
    """
    if severity not in SAFETY_SEVERITIES:
        raise ValueError(f"severity={severity!r} not in SAFETY_SEVERITIES")
    return severity in PUSH_ALERT_SEVERITIES


# ---------------------------------------------------------------------------
# Fact key helpers (§7.1)
# ---------------------------------------------------------------------------

def _normalize_segment(segment: str) -> str:
    """Lowercase, collapse whitespace to underscores."""
    return re.sub(r"\s+", "_", segment.strip()).lower()


def make_fact_key(*parts: str) -> str:
    """Build a normalised fact key from concept parts.

    Args:
        *parts: two or more strings, e.g. ("allergy", "Penicillin") or
                ("lab", "RBC", "2024-11-02").

    Returns:
        Colon-joined normalised key, e.g. "allergy:penicillin".

    Raises:
        ValueError: if any part is empty or whitespace-only.
    """
    for part in parts:
        if not part or not part.strip():
            raise ValueError(f"fact_key part must not be empty: {parts!r}")
    return ":".join(_normalize_segment(p) for p in parts)


# ---------------------------------------------------------------------------
# Fact transition helpers (§7.2)
# ---------------------------------------------------------------------------

def supersede(fact: Dict[str, Any], new_fact_id: str, *, retracted: bool = False) -> Dict[str, Any]:
    """Return a copy of fact with its status updated to superseded or retracted.

    The original dict is not mutated.

    Args:
        fact: an active fact dict (must have status="active").
        new_fact_id: the id of the incoming fact that replaces this one.
        retracted: True when the fact is being withdrawn rather than updated.

    Returns:
        A shallow copy with status and superseded_by updated.

    Raises:
        ValueError: if the fact is already superseded or retracted.
    """
    if fact.get("status") != "active":
        raise ValueError(
            f"cannot supersede fact with status={fact.get('status')!r}; only 'active' facts may be replaced"
        )
    updated = {**fact}
    updated["status"] = "retracted" if retracted else "superseded"
    updated["superseded_by"] = new_fact_id
    return updated


def duplicate_active_keys(facts: List[Dict[str, Any]]) -> List[str]:
    """Return fact_keys that have more than one active entry.

    Args:
        facts: list of fact dicts, each with fact_key and status fields.

    Returns:
        Sorted list of fact_keys with duplicate active entries.
    """
    active_counts: Dict[str, int] = {}
    for f in facts:
        if f.get("status") == "active":
            key = f["fact_key"]
            active_counts[key] = active_counts.get(key, 0) + 1
    return sorted(k for k, count in active_counts.items() if count > 1)


# ---------------------------------------------------------------------------
# Compile job envelope (§7.3)
# ---------------------------------------------------------------------------

class CompileJob(TypedDict):
    """Input envelope passed to the Lane B compile pipeline."""
    session_id: str
    base_draft_version: str
    new_segment_ids: List[str]
    new_document_ids: List[str]
    full_recompute: bool


# ---------------------------------------------------------------------------
# Safety output types (§7.4)
# ---------------------------------------------------------------------------

class SafetyAlertCard(TypedDict):
    """Push alert surfaced to the clinician when severity >= critical/major."""
    severity: SafetySeverity
    fact_keys: List[str]
    evidence: List[str]              # citation ids supporting the alert
    session_id: str
    rule_id: Optional[str]          # which safety rule triggered (None = model-driven)
    acknowledged: bool


class LaneBOutputs(TypedDict):
    """Combined outputs from a Lane B compile run."""
    session_id: str
    draft_version: str
    facts: List[Dict[str, Any]]
    safety_alerts: List[SafetyAlertCard]
    review_state: ReviewState
    compile_job_id: str
