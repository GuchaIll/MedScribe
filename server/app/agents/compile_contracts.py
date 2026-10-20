"""
Lane B compile contracts — v1.2 (Phase 1A, #50).

Defines the fact-lifecycle types and helpers used by the compile pipeline
(Lane B): fact keys, status transitions, review state, delta-action table,
safety push alerts, and the compile job envelope.

Semantics and change control: docs/copilot_runtime_contract.md §7.

Review lives in Postgres review_items (SDD §4.7). ReviewState here is a derived
enum: computed from review_items and the chart write record, never stored, and
read only by DELTA_ACTION in delta compile (#62).
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, TypedDict, get_args

from app.agents.tool_contracts import SOURCE_KINDS, Citation, ContractViolationError


# ---------------------------------------------------------------------------
# Fact lifecycle (§7.1)
# ---------------------------------------------------------------------------

FactStatus = Literal["active", "superseded", "retracted", "needs_review"]
FACT_STATUSES: Tuple[str, ...] = get_args(FactStatus)

# Derived, never stored; only reader is DELTA_ACTION (#62).
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

SafetyAlertType = Literal["allergy", "interaction", "contraindication"]
SAFETY_ALERT_TYPES: Tuple[str, ...] = get_args(SafetyAlertType)

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
    if len(parts) < 2:
        raise ValueError("fact_key requires a canonical type and an entity")
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

class FactProvenance(TypedDict):
    """Where a candidate fact came from. Evidence uses the same Citation every
    tool returns, so extraction output is cited with no translation layer.
    Confidence lives on the fact, not here."""
    evidence: List[Citation]
    extractor: str                  # extraction stage or model id
    prompt_version: str             # prompt registry version (#48) used for extraction


class FactIdentity(TypedDict):
    """Identity and lifecycle fields shared by compile, review, and delta compile."""
    fact_id: str
    fact_key: str
    status: FactStatus
    superseded_by: Optional[str]
    confidence: Optional[float]


class CandidateFact(FactIdentity):
    """Compile candidate with its extracted clinical payload and provenance."""
    type: str
    value: Any
    provenance: FactProvenance


def fact_source_ids(fact: Dict[str, Any], source_kind: str) -> List[str]:
    """The source_ids of one kind that a fact's evidence cites, in order, once each.

    The one way to read the documents (source_kind="document") or transcript
    segments ("session_transcript") a fact came from; they are not stored as
    separate lists.

    Raises:
        ContractViolationError: unknown source_kind, or the fact has no provenance evidence list.
    """
    if source_kind not in SOURCE_KINDS:
        raise ContractViolationError(f"source_kind={source_kind!r} not in {SOURCE_KINDS}")
    provenance = fact.get("provenance")
    evidence = provenance.get("evidence") if isinstance(provenance, dict) else None
    if not isinstance(evidence, list):
        raise ContractViolationError(
            f"fact_id={fact.get('fact_id')!r} has no provenance.evidence list; expected FactProvenance"
        )
    ids: List[str] = []
    for citation in evidence:
        if isinstance(citation, dict) and citation.get("source_kind") == source_kind:
            source_id = citation.get("source_id")
            if source_id and source_id not in ids:
                ids.append(source_id)
    return ids


class CompileJob(TypedDict):
    """Input envelope passed to the Lane B compile pipeline."""
    session_id: str
    base_draft_version: str
    new_segment_ids: List[str]
    new_doc_ids: List[str]
    full_recompute: bool


# ---------------------------------------------------------------------------
# Safety output types (§7.4)
# ---------------------------------------------------------------------------

class SafetyAlertCard(TypedDict):
    """Push alert surfaced to the clinician when severity >= critical/major."""
    alert_id: str
    session_id: str
    alert_type: SafetyAlertType
    severity: SafetySeverity
    message: str
    fact_keys: List[str]
    evidence: List[Citation]


class LaneBOutputs(TypedDict):
    """Combined outputs from a Lane B compile run."""
    draft_version: str
    candidate_facts: List[CandidateFact]
    structured_record: Dict[str, Any]
    validation_report: Dict[str, Any]
    safety_alerts: List[SafetyAlertCard]
