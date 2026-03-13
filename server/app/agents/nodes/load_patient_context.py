"""
Load Patient Context Node — Hydrates pipeline state from database.

Runs immediately after greeting_node to populate patient_record_fields
with the patient's prior clinical history from:
  1. Patient demographics (patients table)
  2. Most recent finalized MedicalRecord (medical_records table)
  3. Prior clinical facts via embedding search (clinical_embeddings table)

If no DB services are available, the pipeline degrades gracefully
and proceeds with empty patient context (same as before this node existed).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import AgentContext
from ..state import GraphState

logger = logging.getLogger(__name__)


def load_patient_context_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Hydrate patient_record_fields from the database.

    Populates:
      - state["patient_record_fields"]["demographics"]: name, dob, age, sex, mrn
      - state["patient_record_fields"]["prior_record"]: last finalized structured_data
      - state["patient_record_fields"]["prior_facts"]: grouped clinical facts from embeddings
      - state["patient_record_fields"]["visit_count"]: total prior visits

    Falls back to empty context if DB is unavailable.
    """
    state = {**state}
    patient_id = state.get("patient_id", "")
    controls = state.get("controls", {"attempts": {}, "budget": {}, "trace_log": []})

    patient_context: Dict[str, Any] = {
        "demographics": {},
        "prior_record": {},
        "prior_facts": {},
        "visit_count": 0,
        "loaded_from_db": False,
    }

    if not patient_id:
        logger.warning("[LoadPatientContext] No patient_id in state — skipping DB lookup")
        state["patient_record_fields"] = patient_context
        _trace(controls, "skipped", "no_patient_id")
        return state

    # ── Fast path: skip DB lookups for new patients ─────────────────────────
    if state.get("is_new_patient"):
        logger.info("[LoadPatientContext] is_new_patient=True — skipping DB lookups")
        state["patient_record_fields"] = patient_context
        _trace(controls, "skipped", "new_patient")
        return state

    # ── 1. Load demographics from Patient table ─────────────────────────────
    if ctx.patient_repo is not None:
        try:
            patient = ctx.patient_repo.get_by_id(patient_id)
            if patient:
                patient_context["demographics"] = {
                    "full_name": patient.full_name,
                    "dob": patient.dob.isoformat() if patient.dob else None,
                    "age": patient.age,
                    "sex": patient.sex,
                    "mrn": patient.mrn,
                }
                logger.info(f"[LoadPatientContext] Loaded demographics for patient {patient_id}")
            else:
                logger.info(f"[LoadPatientContext] Patient {patient_id} not found in DB (new patient)")
        except Exception as e:
            logger.error(f"[LoadPatientContext] Failed to load demographics: {e}")

    # ── 2. Load most recent finalized MedicalRecord ─────────────────────────
    if ctx.record_repo is not None:
        try:
            records = ctx.record_repo.get_for_patient(patient_id, limit=1)
            if records:
                latest = records[0]
                patient_context["prior_record"] = latest.structured_data or {}
                # Use COUNT query instead of fetching all records
                patient_context["visit_count"] = ctx.record_repo.count_for_patient(patient_id)
                logger.info(
                    f"[LoadPatientContext] Loaded prior record (version={latest.version}, "
                    f"is_final={latest.is_final})"
                )
        except Exception as e:
            logger.error(f"[LoadPatientContext] Failed to load prior records: {e}")

    # ── 3. Load clinical fact embeddings (grouped by type) ──────────────────
    if ctx.embedding_service is not None:
        try:
            grouped_facts = ctx.embedding_service.get_all_patient_facts(
                patient_id=patient_id,
                only_final=True,
            )
            patient_context["prior_facts"] = grouped_facts
            total_facts = sum(len(v) for v in grouped_facts.values())
            logger.info(
                f"[LoadPatientContext] Loaded {total_facts} prior facts across "
                f"{len(grouped_facts)} categories"
            )
        except Exception as e:
            logger.error(f"[LoadPatientContext] Failed to load clinical embeddings: {e}")

    patient_context["loaded_from_db"] = bool(
        patient_context["demographics"] or patient_context["prior_record"] or patient_context["prior_facts"]
    )

    state["patient_record_fields"] = patient_context
    _trace(
        controls,
        "loaded" if patient_context["loaded_from_db"] else "empty",
        f"demographics={bool(patient_context['demographics'])}, "
        f"prior_record={bool(patient_context['prior_record'])}, "
        f"prior_facts={sum(len(v) for v in patient_context['prior_facts'].values())} facts",
    )

    return state


def _trace(controls: Dict[str, Any], action: str, detail: str) -> None:
    """Append a trace log entry."""
    controls.setdefault("trace_log", []).append({
        "node": "load_patient_context",
        "action": action,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
    })
