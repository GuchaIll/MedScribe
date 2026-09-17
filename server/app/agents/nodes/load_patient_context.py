"""
Load Patient Context Node — hydrates pipeline state from the session snapshot.

Since #51 this node no longer reads the database itself. It asks the session
snapshot (plan §6.1), which loads once per session and is reused by the assist
path, the safety tools, and ``get_patient_profile``. The second compile in a
session is a cache hit, not a second full reload.

Outputs (unchanged for downstream nodes):
  - state["patient_record_fields"]["demographics"]
  - state["patient_record_fields"]["prior_record"]
  - state["patient_record_fields"]["prior_facts"]   (grouped by fact type)
  - state["patient_record_fields"]["visit_count"]
plus ``snapshot_version`` and ``snapshot_source`` so later stages can cite the
snapshot they read.

If no patient state exists, the pipeline degrades exactly as before: empty
context, no exception.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from ..config import AgentContext
from ..session.snapshot import PatientContextSnapshot, SnapshotStore, load_snapshot
from ..state import GraphState

logger = logging.getLogger(__name__)


def load_patient_context_node(
    state: GraphState,
    ctx: Optional[AgentContext] = None,
    *,
    store: Optional[SnapshotStore] = None,
) -> GraphState:
    """Hydrate patient_record_fields from the session snapshot."""
    state = {**state}
    patient_id = state.get("patient_id", "")
    session_id = state.get("session_id") or ""
    controls = state.get("controls", {"attempts": {}, "budget": {}, "trace_log": []})

    if not patient_id:
        logger.warning("[LoadPatientContext] no patient_id in state — skipping snapshot load")
        state["patient_record_fields"] = _fields(None)
        _trace(controls, "skipped", "no_patient_id")
        return state

    if not session_id:
        # Without a session key there is nothing to cache under; load per compile
        # and say so, rather than silently sharing one patient's snapshot.
        logger.warning(
            "[LoadPatientContext] no session_id in state — loading without the session cache"
        )

    if state.get("is_new_patient"):
        logger.info("[LoadPatientContext] is_new_patient=True — skipping snapshot load")
        state["patient_record_fields"] = _fields(None)
        _trace(controls, "skipped", "new_patient")
        return state

    try:
        snapshot = load_snapshot(
            session_id or f"compile:{patient_id}",
            patient_id,
            ctx,
            tenant_id=state.get("tenant_id"),
            store=store,
        )
    except Exception as exc:
        logger.exception("[LoadPatientContext] snapshot load failed for patient_id=%s", patient_id)
        state["patient_record_fields"] = _fields(None)
        _trace(controls, "error", f"snapshot_load_failed: {type(exc).__name__}")
        return state

    fields = _fields(snapshot)
    state["patient_record_fields"] = fields
    fact_count = sum(len(rows) for rows in fields["prior_facts"].values())
    logger.info(
        "[LoadPatientContext] snapshot source=%s version=%s facts=%d visits=%d",
        snapshot["source"], snapshot["version"], fact_count, snapshot["visit_count"],
    )
    _trace(
        controls,
        "loaded" if fields["loaded_from_db"] else "empty",
        f"source={snapshot['source']}, version={snapshot['version']}, "
        f"demographics={bool(fields['demographics'])}, "
        f"prior_record={bool(fields['prior_record'])}, prior_facts={fact_count} facts",
    )
    return state


def _fields(snapshot: Optional[PatientContextSnapshot]) -> Dict[str, Any]:
    """Map a snapshot onto the patient_record_fields shape downstream nodes read."""
    if snapshot is None:
        return {
            "demographics": {},
            "prior_record": {},
            "prior_facts": {},
            "visit_count": 0,
            "loaded_from_db": False,
            "snapshot_version": 0,
            "snapshot_source": "empty",
        }
    return {
        "demographics": snapshot["demographics"],
        "prior_record": snapshot["prior_record"],
        "prior_facts": snapshot["facts_by_type"],
        "visit_count": snapshot["visit_count"],
        "loaded_from_db": snapshot["loaded_from_db"],
        "snapshot_version": snapshot["version"],
        "snapshot_source": snapshot["source"],
    }


def _trace(controls: Dict[str, Any], action: str, detail: str) -> None:
    """Append a trace log entry."""
    controls.setdefault("trace_log", []).append({
        "node": "load_patient_context",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
    })
