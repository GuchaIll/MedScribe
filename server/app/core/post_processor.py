"""
Post-Session Processing Service.

Runs after a medical record is finalized to:
  1. Re-evaluate clinical suggestions against the final record
  2. Generate/update clinical embeddings for new facts
  3. Compute patient risk profile delta
  4. Write audit trail entries

Usage::

    from app.core.post_processor import get_post_processor

    processor = get_post_processor()
    result = await processor.run(session_id, final_record, patient_id, doctor_id)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PostProcessor:
    """
    Post-session analysis after record finalization.

    Orchestrates re-evaluation of clinical safety checks, embedding
    generation for long-term retrieval, and risk scoring.
    """

    def __init__(self):
        self._clinical_engine = None

    async def run(
        self,
        session_id: str,
        final_record: Dict[str, Any],
        patient_id: str,
        doctor_id: str,
        *,
        patient_history: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute full post-processing pipeline.

        Parameters
        ----------
        session_id : str
        final_record : dict
            The finalized structured medical record.
        patient_id, doctor_id : str
        patient_history : dict, optional
            If not provided, attempts to load from DB.

        Returns
        -------
        dict
            Summary of post-processing results.
        """
        results: Dict[str, Any] = {
            "session_id": session_id,
            "patient_id": patient_id,
            "steps_completed": [],
            "clinical_recheck": None,
            "embeddings_stored": 0,
            "risk_delta": None,
            "errors": [],
        }

        # Step 1: Re-evaluate clinical suggestions on final record
        try:
            recheck = self._recheck_clinical_suggestions(
                final_record, patient_id, patient_history
            )
            results["clinical_recheck"] = recheck
            results["steps_completed"].append("clinical_recheck")
        except Exception as e:
            logger.warning("Post-processing: clinical re-check failed: %s", e)
            results["errors"].append(f"clinical_recheck: {e}")

        # Step 2: Generate embeddings for new clinical facts
        try:
            count = self._store_new_embeddings(
                final_record, patient_id, session_id
            )
            results["embeddings_stored"] = count
            results["steps_completed"].append("embeddings")
        except Exception as e:
            logger.warning("Post-processing: embedding storage failed: %s", e)
            results["errors"].append(f"embeddings: {e}")

        # Step 3: Compute risk profile delta
        try:
            risk = self._compute_risk_delta(final_record, patient_id)
            results["risk_delta"] = risk
            results["steps_completed"].append("risk_delta")
        except Exception as e:
            logger.warning("Post-processing: risk delta failed: %s", e)
            results["errors"].append(f"risk_delta: {e}")

        # Step 4: Audit trail
        try:
            self._write_post_processing_audit(
                session_id, patient_id, doctor_id, results
            )
            results["steps_completed"].append("audit")
        except Exception as e:
            logger.warning("Post-processing: audit failed: %s", e)
            results["errors"].append(f"audit: {e}")

        logger.info(
            "[PostProcessor] session=%s completed steps=%s errors=%d",
            session_id,
            results["steps_completed"],
            len(results["errors"]),
        )

        return results

    # ── Step 1: Clinical re-check ──────────────────────────────────────────

    def _recheck_clinical_suggestions(
        self,
        final_record: Dict[str, Any],
        patient_id: str,
        patient_history: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Re-run CDS engine on the finalized record."""
        from app.core.clinical_suggestions import get_clinical_suggestion_engine

        engine = get_clinical_suggestion_engine()

        history = patient_history
        if history is None:
            # Build minimal history from the record itself
            history = {
                "found": True,
                "allergies": final_record.get("allergies", []),
                "medications": [],
                "diagnoses": final_record.get("diagnoses", []),
                "labs": final_record.get("labs", []),
            }

        suggestions = engine.generate_suggestions(
            current_record=final_record,
            patient_history=history,
        )

        return {
            "risk_level": suggestions.get("risk_level", "low"),
            "allergy_alerts": len(suggestions.get("allergy_alerts", [])),
            "drug_interactions": len(suggestions.get("drug_interactions", [])),
            "contraindications": len(suggestions.get("contraindications", [])),
            "dosage_issues": len(suggestions.get("dosage_issues", [])),
            "total_alerts": sum(
                len(suggestions.get(k, []))
                for k in ("allergy_alerts", "drug_interactions", "contraindications", "dosage_issues")
            ),
        }

    # ── Step 2: Embedding storage ──────────────────────────────────────────

    def _store_new_embeddings(
        self,
        final_record: Dict[str, Any],
        patient_id: str,
        session_id: str,
    ) -> int:
        """
        Extract clinical facts from the finalized record and store
        as embeddings for future retrieval.
        """
        facts = self._extract_facts_from_record(final_record)

        if not facts:
            return 0

        stored = 0
        try:
            from app.services.embedding_service import get_embedding_service
            embedding_svc = get_embedding_service()
            if embedding_svc is None:
                logger.debug("Embedding service not available — skipping")
                return 0

            for fact in facts:
                try:
                    embedding_svc.store_clinical_embedding(
                        patient_id=patient_id,
                        session_id=session_id,
                        fact=fact,
                        record_id=None,
                        source_span=fact.get("source_text", ""),
                        grounding_score=0.9,  # Finalized record has high trust
                        is_final=True,
                    )
                    stored += 1
                except Exception:
                    pass
        except ImportError:
            logger.debug("Embedding service not importable — skipping")

        return stored

    def _extract_facts_from_record(
        self, record: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Pull candidate facts from a structured record for embedding."""
        facts: List[Dict[str, Any]] = []

        # Diagnoses → facts
        for dx in record.get("diagnoses", []):
            if isinstance(dx, dict) and dx.get("description"):
                facts.append({
                    "fact_id": str(uuid.uuid4()),
                    "type": "diagnosis",
                    "value": dx.get("description", ""),
                    "provenance": "finalized_record",
                    "confidence": 0.95,
                    "source_text": f"Diagnosis: {dx.get('description')} (ICD: {dx.get('code', '')})",
                })

        # Medications → facts
        for med in record.get("medications", []):
            if isinstance(med, dict) and med.get("name"):
                facts.append({
                    "fact_id": str(uuid.uuid4()),
                    "type": "medication",
                    "value": med.get("name", ""),
                    "provenance": "finalized_record",
                    "confidence": 0.95,
                    "source_text": (
                        f"Medication: {med.get('name')} {med.get('dose', '')} "
                        f"{med.get('route', '')} {med.get('frequency', '')}"
                    ).strip(),
                })

        # Allergies → facts
        for allergy in record.get("allergies", []):
            if isinstance(allergy, dict) and allergy.get("substance"):
                facts.append({
                    "fact_id": str(uuid.uuid4()),
                    "type": "allergy",
                    "value": allergy.get("substance", ""),
                    "provenance": "finalized_record",
                    "confidence": 0.98,
                    "source_text": (
                        f"Allergy: {allergy.get('substance')} — "
                        f"{allergy.get('reaction', 'unspecified reaction')}"
                    ),
                })

        # Lab values → facts
        for lab in record.get("labs", []):
            if isinstance(lab, dict) and lab.get("test_name"):
                facts.append({
                    "fact_id": str(uuid.uuid4()),
                    "type": "lab_result",
                    "value": f"{lab.get('test_name')}: {lab.get('value')} {lab.get('unit', '')}",
                    "provenance": "finalized_record",
                    "confidence": 0.9,
                    "source_text": (
                        f"{lab.get('test_name')} = {lab.get('value')} {lab.get('unit', '')} "
                        f"(ref: {lab.get('reference_range', '—')})"
                    ),
                })

        return facts

    # ── Step 3: Risk delta ─────────────────────────────────────────────────

    def _compute_risk_delta(
        self, final_record: Dict[str, Any], patient_id: str
    ) -> Dict[str, Any]:
        """
        Compute simple risk score based on the finalized record content.

        A more sophisticated version would compare against the patient's
        prior baseline from the long-term model.
        """
        risk_factors = 0
        risk_details: List[str] = []

        # Count active high-risk conditions
        for dx in final_record.get("diagnoses", []):
            if isinstance(dx, dict):
                desc = (dx.get("description") or "").lower()
                if any(kw in desc for kw in (
                    "diabetes", "hypertension", "ckd", "heart failure",
                    "copd", "cancer", "stroke", "cirrhosis",
                )):
                    risk_factors += 2
                    risk_details.append(f"High-risk condition: {dx.get('description')}")

        # Polypharmacy risk
        med_count = len(final_record.get("medications", []))
        if med_count > 10:
            risk_factors += 3
            risk_details.append(f"Polypharmacy ({med_count} medications)")
        elif med_count > 5:
            risk_factors += 1
            risk_details.append(f"Multiple medications ({med_count})")

        # Allergy count
        allergy_count = len(final_record.get("allergies", []))
        if allergy_count > 3:
            risk_factors += 1
            risk_details.append(f"Multiple allergies ({allergy_count})")

        # Abnormal labs
        abnormal_labs = [
            lab for lab in final_record.get("labs", [])
            if isinstance(lab, dict) and lab.get("abnormal")
        ]
        if len(abnormal_labs) > 3:
            risk_factors += 2
            risk_details.append(f"Multiple abnormal labs ({len(abnormal_labs)})")
        elif abnormal_labs:
            risk_factors += 1

        # Score → level
        if risk_factors >= 6:
            level = "high"
        elif risk_factors >= 3:
            level = "moderate"
        else:
            level = "low"

        return {
            "score": risk_factors,
            "level": level,
            "factors": risk_details,
            "computed_at": datetime.utcnow().isoformat(),
        }

    # ── Step 4: Audit ──────────────────────────────────────────────────────

    def _write_post_processing_audit(
        self,
        session_id: str,
        patient_id: str,
        doctor_id: str,
        results: Dict[str, Any],
    ) -> None:
        """Write post-processing completion to the audit log."""
        try:
            from contextlib import contextmanager
            from app.database.session import get_db_context
            from app.database.models import AuditLog

            # get_db_context is a generator — wrap it as a context manager
            db_ctx = contextmanager(get_db_context)
            with db_ctx() as db:
                audit = AuditLog(
                    user_id=doctor_id,
                    user_role="doctor",
                    action="post_processing_complete",
                    resource_type="session",
                    resource_id=session_id,
                    details={
                        "patient_id": patient_id,
                        "steps_completed": results.get("steps_completed", []),
                        "embeddings_stored": results.get("embeddings_stored", 0),
                        "risk_level": (results.get("risk_delta") or {}).get("level"),
                        "errors": results.get("errors", []),
                    },
                    success=len(results.get("errors", [])) == 0,
                )
                db.add(audit)
                # commit handled by context manager

        except Exception as e:
            logger.warning("Post-processing audit log failed: %s", e)


# ── Factory ─────────────────────────────────────────────────────────────────

_instance: Optional[PostProcessor] = None


def get_post_processor() -> PostProcessor:
    """Return a singleton PostProcessor."""
    global _instance
    if _instance is None:
        _instance = PostProcessor()
    return _instance
