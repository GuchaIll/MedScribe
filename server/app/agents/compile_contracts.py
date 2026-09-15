"""
Lane B output contract — frozen v1 (agent refactor Phase 0).

What a compile run hands back, how background compiles merge instead of
clobbering (delta-compile semantics), and the push safety alert card that
appears without the clinician asking. Types, tables, and small pure helpers
only: push alerts ship in Phase 3, delta compile in Phase 4.

Semantics: docs/copilot_runtime_contract.md §7.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Sequence, Tuple, TypedDict, get_args

from app.agents.tool_contracts import Citation


# ---------------------------------------------------------------------------
# Delta compile: fact identity and supersession
# ---------------------------------------------------------------------------

FactStatus = Literal["active", "superseded", "retracted", "needs_review"]
FACT_STATUSES: Tuple[str, ...] = get_args(FactStatus)

# canonical_type:entity[:qualifier] — e.g. allergy:amoxicillin, lab:rbc:2024-11-02, med:lisinopril
FACT_KEY_PATTERN = re.compile(r"^[a-z][a-z_]*:[a-z0-9][a-z0-9_.-]*(?::[a-z0-9][a-z0-9_.-]*)?$")


class FactIdentity(TypedDict):
    """Delta-compile fields every CandidateFact carries from Phase 4 on (additive to state.CandidateFact)."""
    fact_key: str
    fact_id: str                    # uuid per observation instance
    status: FactStatus
    superseded_by: Optional[str]    # fact_id of the replacing observation
    source_segment_ids: List[str]   # kept on old and new claims so audit shows the self-correction
    source_doc_ids: List[str]
    confidence: Optional[float]


class CompileJob(TypedDict):
    session_id: str
    base_draft_version: int         # stale version => rebase or retry, never clobber
    new_segment_ids: List[str]      # delta only when possible
    new_document_ids: List[str]
    full_recompute: bool            # rare: end-session or corruption recovery


# Where a fact already sits when a later compile contradicts it
ReviewState = Literal["working_draft", "open_review", "approved_pending_write", "persisted"]
DeltaAction = Literal["merge", "attach_delta_note", "open_new_review_item"]

REVIEW_STATES: Tuple[str, ...] = get_args(ReviewState)
DELTA_ACTIONS: Tuple[str, ...] = get_args(DeltaAction)

DELTA_ACTION: Dict[str, str] = {
    "working_draft": "merge",
    # Bump the package version and mark the UI dirty; never silently remove or downgrade the queued item.
    "open_review": "attach_delta_note",
    # Approval is sticky: contradicting evidence opens a new item instead of un-approving.
    "approved_pending_write": "open_new_review_item",
    "persisted": "open_new_review_item",
}


def _key_part(part: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", part.strip().lower()).strip("_")


def make_fact_key(canonical_type: str, entity: str, qualifier: Optional[str] = None) -> str:
    """Build a normalized fact_key, e.g. ("lab", "RBC", "2024-11-02") -> "lab:rbc:2024-11-02"."""
    parts = [canonical_type, entity] + ([qualifier] if qualifier else [])
    key = ":".join(_key_part(p) for p in parts)
    if not FACT_KEY_PATTERN.match(key):
        raise ValueError(f"cannot build a fact_key from {parts!r}")
    return key


def supersede(prior: FactIdentity, replacement_fact_id: str, *, retracted: bool = False) -> FactIdentity:
    """Mark a prior observation superseded (or retracted when explicitly negated). Never deletes it."""
    if prior["status"] not in ("active", "needs_review"):
        raise ValueError(f"fact {prior['fact_id']!r} is already {prior['status']}")
    updated: FactIdentity = {
        **prior,
        "status": "retracted" if retracted else "superseded",
        "superseded_by": replacement_fact_id,
    }
    return updated


def duplicate_active_keys(facts: Sequence[FactIdentity]) -> List[str]:
    """fact_keys with more than one active fact. A materialized draft must have none."""
    seen: set = set()
    duplicates: set = set()
    for fact in facts:
        if fact["status"] != "active":
            continue
        if fact["fact_key"] in seen:
            duplicates.add(fact["fact_key"])
        seen.add(fact["fact_key"])
    return sorted(duplicates)


# ---------------------------------------------------------------------------
# Push safety and compile outputs
# ---------------------------------------------------------------------------

# Same severity vocabulary app/core/clinical_suggestions.py already emits
SafetySeverity = Literal["critical", "major", "moderate", "info"]
SafetyAlertType = Literal["allergy", "interaction", "contraindication"]

SAFETY_SEVERITIES: Tuple[str, ...] = get_args(SafetySeverity)
SAFETY_ALERT_TYPES: Tuple[str, ...] = get_args(SafetyAlertType)

# Provisional: severities that render an alert card mid-visit. Lower severities
# attach to the draft / review panel without interrupting.
PUSH_ALERT_SEVERITIES: FrozenSet[str] = frozenset({"critical", "major"})


class SafetyAlertCard(TypedDict):
    alert_id: str
    session_id: str
    alert_type: SafetyAlertType
    severity: SafetySeverity
    message: str
    fact_keys: List[str]
    evidence: List[Citation]


class LaneBOutputs(TypedDict):
    """What every compile run returns (plan §3.3). Not necessarily a SOAP note."""
    draft_version: int
    candidate_facts: List[Dict[str, Any]]       # state.CandidateFact + FactIdentity fields
    structured_record: Dict[str, Any]
    validation_report: Optional[Dict[str, Any]]
    safety_alerts: List[SafetyAlertCard]        # push path; always present, may be empty
    review_package: Optional[Dict[str, Any]]


def renders_alert_card(severity: str) -> bool:
    """Whether a push safety alert interrupts with an alert card."""
    if severity not in SAFETY_SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")
    return severity in PUSH_ALERT_SEVERITIES
