"""
Persist Results Node — Writes pipeline outputs to the database.

Runs as the final node before END to:
  1. Create / update a MedicalRecord with the structured record + SOAP note
  2. Store clinical fact embeddings (with Layer 3 confidence gating)
  3. Update Session status to COMPLETED
  4. Create an AuditLog entry for the pipeline run

If no DB services are available, the node is a no-op (pipeline still
produces file-based outputs via package_outputs_node).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import AgentContext
from ..state import GraphState

logger = logging.getLogger(__name__)


def persist_results_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Persist pipeline results to the database.

    Operations (all best-effort — partial failures don't block the pipeline):
      1. Upsert MedicalRecord  (record_repo)
      2. Store clinical fact embeddings  (embedding_service)
      3. Mark Session as completed  (session_repo)
      4. Write AuditLog entry  (db_session_factory)
    """
    state = {**state}
    controls = state.get("controls", {"attempts": {}, "budget": {}, "trace_log": []})
    patient_id = state.get("patient_id", "")
    session_id = state.get("session_id", "")
    doctor_id = state.get("doctor_id", "")

    persisted: Dict[str, bool] = {
        "medical_record": False,
        "clinical_embeddings": False,
        "session_status": False,
        "audit_log": False,
    }

    # ── 1. Create / update MedicalRecord ────────────────────────────────────
    record_id = _persist_medical_record(
        ctx, state, patient_id, session_id, doctor_id, persisted
    )

    # ── 2. Store clinical fact embeddings ───────────────────────────────────
    _persist_clinical_embeddings(
        ctx, state, patient_id, session_id, record_id, persisted
    )

    # ── 3. Update session status ────────────────────────────────────────────
    _update_session_status(ctx, session_id, persisted)

    # ── 4. Audit log ────────────────────────────────────────────────────────
    _write_audit_log(ctx, patient_id, session_id, doctor_id, record_id, persisted)

    # ── Commit all changes ──────────────────────────────────────────────────
    if ctx.db_session_factory is not None:
        try:
            # The repos share the same session — commit once
            if ctx.record_repo and ctx.record_repo.db:
                ctx.record_repo.db.commit()
                logger.info("[PersistResults] Committed all DB changes")
        except Exception as e:
            logger.error(f"[PersistResults] Commit failed: {e}")
            if ctx.record_repo and ctx.record_repo.db:
                ctx.record_repo.db.rollback()

    # ── 5. Trigger post-processing (best-effort, non-blocking) ──────────
    _trigger_post_processing(state, patient_id, session_id, doctor_id)

    # Trace
    controls.setdefault("trace_log", []).append({
        "node": "persist_results",
        "action": "persisted",
        "detail": persisted,
        "record_id": record_id,
        "timestamp": datetime.now().isoformat(),
    })
    state["controls"] = controls

    summary = ", ".join(f"{k}={'OK' if v else 'SKIP'}" for k, v in persisted.items())
    state["message"] = (state.get("message") or "") + f" | DB persist: {summary}"
    logger.info(f"[PersistResults] {summary}")

    return state


# ─── Internal helpers ───────────────────────────────────────────────────────

def _persist_medical_record(
    ctx: AgentContext,
    state: GraphState,
    patient_id: str,
    session_id: str,
    doctor_id: str,
    persisted: Dict[str, bool],
) -> Optional[str]:
    """Create or update MedicalRecord with automatic version incrementing."""
    if ctx.record_repo is None:
        return None

    # Skip DB persist when patient_id is missing — the FK constraint on
    # medical_records requires a valid patients row.
    if not patient_id:
        logger.info("[PersistResults] No patient_id — skipping MedicalRecord insert")
        return None

    record_id = str(uuid.uuid4())

    try:
        from app.database.models import MedicalRecord

        structured_data = state.get("structured_record", {})
        clinical_suggestions = state.get("clinical_suggestions")
        soap_note = state.get("clinical_note")
        validation_report = state.get("validation_report")
        conflict_report = state.get("conflict_report")

        # Compute overall confidence from validation
        confidence_score = None
        if validation_report:
            errors = len(validation_report.get("schema_errors", []))
            missing = len(validation_report.get("missing_fields", []))
            conflicts = len(validation_report.get("conflicts", []))
            # Simple heuristic: 100 - (10 * errors) - (5 * missing) - (15 * conflicts)
            confidence_score = max(0, 100 - (10 * errors) - (5 * missing) - (15 * conflicts))

        # Determine if record should be finalized
        needs_review = (validation_report or {}).get("needs_review", False)
        is_final = not needs_review and (confidence_score or 0) >= 80

        # ── Version incrementing: check for existing records for this session ──
        version = 1
        try:
            db = ctx.record_repo.db
            if db is not None:
                existing = (
                    db.query(MedicalRecord)
                    .filter(MedicalRecord.session_id == session_id)
                    .order_by(MedicalRecord.version.desc())
                    .first()
                )
                if existing:
                    version = (existing.version or 0) + 1
                    logger.info(
                        f"[PersistResults] Found existing record v{existing.version} "
                        f"for session {session_id}, creating v{version}"
                    )
        except Exception as ve:
            logger.debug(f"[PersistResults] Version check skipped: {ve}")

        record = MedicalRecord(
            id=record_id,
            patient_id=patient_id,
            session_id=session_id,
            structured_data=structured_data,
            clinical_suggestions=clinical_suggestions,
            soap_note=soap_note,
            validation_report=validation_report,
            conflict_report=conflict_report,
            confidence_score=confidence_score,
            version=version,
            is_final=is_final,
            record_type="SOAP",
            created_by=doctor_id,
        )

        ctx.record_repo.create(record)
        persisted["medical_record"] = True
        logger.info(
            f"[PersistResults] Created MedicalRecord {record_id} "
            f"(v{version}, confidence={confidence_score}, is_final={is_final})"
        )
        return record_id

    except Exception as e:
        logger.error(f"[PersistResults] Failed to create MedicalRecord: {e}")
        return None


def _persist_clinical_embeddings(
    ctx: AgentContext,
    state: GraphState,
    patient_id: str,
    session_id: str,
    record_id: Optional[str],
    persisted: Dict[str, bool],
) -> None:
    """Store each candidate fact as a clinical embedding (Layer 3 gating applied)."""
    if ctx.embedding_service is None or not patient_id:
        return

    candidates = state.get("candidate_facts", [])
    evidence_map = state.get("evidence_map", {})

    stored_count = 0
    skipped_count = 0

    try:
        for fact in candidates:
            fact_id = fact.get("fact_id", "")
            confidence = fact.get("confidence", 0.5)

            # Get the best evidence snippet as source_span
            evidence_items = evidence_map.get(fact_id, [])
            source_span = None
            grounding_score = None

            if evidence_items:
                best_evidence = max(evidence_items, key=lambda e: e.get("confidence", 0))
                source_span = best_evidence.get("snippet", "")

                # Layer 1: Verify grounding
                if source_span:
                    try:
                        grounding_score, is_grounded = ctx.embedding_service.verify_grounding(
                            source_span=source_span,
                            extracted_text=ctx.embedding_service._fact_to_text(fact),
                        )
                        if not is_grounded:
                            logger.warning(
                                f"[PersistResults] Fact {fact_id} failed grounding "
                                f"(score={grounding_score:.3f} < {ctx.grounding_threshold})"
                            )
                            # Still store, but mark is_final=False
                    except Exception:
                        pass

            # Layer 3: Confidence gating applied inside store_clinical_embedding
            is_final = confidence >= ctx.persistence_floor
            if grounding_score is not None and grounding_score < ctx.grounding_threshold:
                is_final = False

            ctx.embedding_service.store_clinical_embedding(
                patient_id=patient_id,
                session_id=session_id,
                fact=fact,
                record_id=record_id,
                source_span=source_span,
                grounding_score=grounding_score,
                is_final=is_final,
            )
            stored_count += 1

        persisted["clinical_embeddings"] = stored_count > 0
        logger.info(
            f"[PersistResults] Stored {stored_count} clinical embeddings, "
            f"skipped {skipped_count}"
        )

    except Exception as e:
        logger.error(f"[PersistResults] Failed to store clinical embeddings: {e}")


def _update_session_status(
    ctx: AgentContext,
    session_id: str,
    persisted: Dict[str, bool],
) -> None:
    """Mark session as completed."""
    if ctx.session_repo is None or not session_id:
        return

    try:
        ctx.session_repo.end_session(session_id)
        persisted["session_status"] = True
        logger.info(f"[PersistResults] Session {session_id} marked as completed")
    except Exception as e:
        logger.error(f"[PersistResults] Failed to update session status: {e}")


def _write_audit_log(
    ctx: AgentContext,
    patient_id: str,
    session_id: str,
    doctor_id: str,
    record_id: Optional[str],
    persisted: Dict[str, bool],
) -> None:
    """Write HIPAA audit trail entry."""
    if ctx.db_session_factory is None:
        return

    # Skip when doctor_id is empty — the FK on audit_logs.user_id requires
    # a valid users row.
    if not doctor_id:
        logger.info("[PersistResults] No doctor_id — skipping AuditLog insert")
        return

    try:
        from app.database.models import AuditLog

        # Use the same session as the repos
        db = None
        if ctx.record_repo and ctx.record_repo.db:
            db = ctx.record_repo.db
        else:
            return

        audit = AuditLog(
            user_id=doctor_id,
            user_role="doctor",
            action="pipeline_complete",
            resource_type="medical_record",
            resource_id=record_id or session_id,
            details={
                "session_id": session_id,
                "patient_id": patient_id,
                "record_id": record_id,
                "persisted": persisted,
            },
            success=True,
        )
        db.add(audit)
        db.flush()
        persisted["audit_log"] = True

    except Exception as e:
        logger.error(f"[PersistResults] Failed to write audit log: {e}")


def _trigger_post_processing(
    state: GraphState,
    patient_id: str,
    session_id: str,
    doctor_id: str,
) -> None:
    """
    Fire-and-forget post-session analysis.

    This runs synchronously for now; a production deployment would push
    this to a background task queue (Celery / ARQ / etc.).
    """
    try:
        from app.core.post_processor import get_post_processor
        import asyncio

        final_record = state.get("structured_record", {})
        if not final_record:
            return

        processor = get_post_processor()

        # If there's a running event loop, schedule; otherwise run_sync.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                processor.run(session_id, final_record, patient_id, doctor_id)
            )
        except RuntimeError:
            asyncio.run(
                processor.run(session_id, final_record, patient_id, doctor_id)
            )

        logger.info("[PersistResults] Post-processing triggered for session %s", session_id)

    except Exception as e:
        # Post-processing failure must never break the pipeline
        logger.warning("[PersistResults] Post-processing trigger failed: %s", e)
