"""
Physician review queue -- Redis-backed staging for unsigned record changes.

When the clinical pipeline produces a record that needs human review
(unresolved conflicts, schema errors, missing critical fields, low
confidence), the durable patient record is NOT mutated. Instead the
proposed record and a flattened list of discrepancies are staged here,
keyed by session, so the physician can review and correct them at the
*end* of the session rather than being blocked mid-encounter.

Persistence only happens after explicit physician sign-off, handled by a
separate review-persist worker (Go gateway, follow-up). This module owns
the staging side: it mirrors the PipelineProgressStore Redis pattern
(self-connecting via REDIS_URL, in-memory fallback for local dev) so the
Go gateway can read the same ``pipeline:review:{session_id}`` key.

Key layout (coexists with pipeline:{id} and pipeline:progress:{id}):
    pipeline:review:{session_id} -> JSON PendingReview
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discrepancy construction
# ---------------------------------------------------------------------------

def _discrepancy(kind: str, message: str, *, source: str, field: Optional[str] = None) -> Dict[str, Any]:
    """Build a single discrepancy row in the shape the review UI/worker expects."""
    return {
        "id": str(uuid.uuid4()),
        "kind": kind,            # schema_error | missing_field | conflict | low_confidence
        "field": field,          # best-effort field name, may be None
        "message": message,      # human-readable description
        "source": source,        # validation | conflict
        "status": "pending",     # pending | approved | rejected (set on sign-off)
    }


def _field_from_message(message: str) -> Optional[str]:
    """Best-effort extraction of a field name from a 'field: detail' string."""
    if ":" in message:
        candidate = message.split(":", 1)[0].strip()
        # Heuristic: treat short, path-like tokens as field names.
        if candidate and len(candidate) <= 60 and " " not in candidate.strip():
            return candidate
    return None


def build_discrepancies(
    validation_report: Optional[Dict[str, Any]],
    conflict_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Flatten validation + conflict reports into a reviewable discrepancy list.

    The underlying reports carry string lists (schema_errors, missing_fields,
    conflicts), so each entry becomes one discrepancy with a best-effort field
    guess. The full reports are also kept in the staged payload for context.
    """
    discrepancies: List[Dict[str, Any]] = []

    if validation_report:
        for err in validation_report.get("schema_errors", []) or []:
            msg = err if isinstance(err, str) else json.dumps(err)
            discrepancies.append(
                _discrepancy("schema_error", msg, source="validation", field=_field_from_message(msg))
            )
        for missing in validation_report.get("missing_fields", []) or []:
            discrepancies.append(
                _discrepancy("missing_field", f"Missing required field: {missing}",
                             source="validation", field=str(missing))
            )
        for conflict in validation_report.get("conflicts", []) or []:
            msg = conflict if isinstance(conflict, str) else json.dumps(conflict)
            discrepancies.append(
                _discrepancy("conflict", msg, source="validation", field=_field_from_message(msg))
            )
        confidence = validation_report.get("confidence")
        if confidence is not None and confidence < 0.7:
            discrepancies.append(
                _discrepancy("low_confidence", f"Low overall confidence: {confidence:.2f}",
                             source="validation")
            )

    if conflict_report:
        for conflict in conflict_report.get("conflicts", []) or []:
            msg = conflict if isinstance(conflict, str) else json.dumps(conflict)
            discrepancies.append(
                _discrepancy("conflict", msg, source="conflict", field=_field_from_message(msg))
            )

    return discrepancies


# ---------------------------------------------------------------------------
# Redis-backed store
# ---------------------------------------------------------------------------

class ReviewQueueStore:
    """
    Redis-backed staging store for pending physician review, keyed by session.

    Falls back to an in-memory dict when Redis is unavailable so local
    development without Redis still works. Mirrors the connection pattern of
    PipelineProgressStore for consistency.
    """

    _KEY_PREFIX = "pipeline:review:"
    _TTL_SECONDS = 86400  # 24 hours

    def __init__(self) -> None:
        self._fallback: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._redis_available = False
        self._connect_redis()

    def _connect_redis(self) -> None:
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            logger.info("review_queue: REDIS_URL not set, using in-memory fallback")
            return
        try:
            import redis as _redis
            self._redis = _redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._redis_available = True
            logger.info("review_queue: connected to Redis at %s", redis_url)
        except Exception as exc:
            logger.warning("review_queue: Redis unavailable (%s), using in-memory fallback", exc)
            self._redis = None
            self._redis_available = False

    def _key(self, session_id: str) -> str:
        return f"{self._KEY_PREFIX}{session_id}"

    def stage_pending_review(
        self,
        session_id: str,
        *,
        patient_id: str,
        doctor_id: str,
        proposed_record: Dict[str, Any],
        discrepancies: List[Dict[str, Any]],
        validation_report: Optional[Dict[str, Any]] = None,
        conflict_report: Optional[Dict[str, Any]] = None,
        clinical_note: Optional[str] = None,
        clinical_suggestions: Optional[Dict[str, Any]] = None,
        confidence_score: Optional[float] = None,
        candidate_facts: Optional[List[Dict[str, Any]]] = None,
        evidence_map: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Stage a proposed record + discrepancies for end-of-session sign-off.

        Nothing here touches the durable patient record. The review-persist
        worker reads this payload on physician sign-off and only then writes
        the approved changes to PostgreSQL.
        """
        payload: Dict[str, Any] = {
            "session_id": session_id,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "status": "pending_review",
            "created_at": datetime.now().isoformat(),
            "discrepancy_count": len(discrepancies),
            "discrepancies": discrepancies,
            "proposed_record": proposed_record,
            "clinical_note": clinical_note,
            "clinical_suggestions": clinical_suggestions,
            "validation_report": validation_report,
            "conflict_report": conflict_report,
            "confidence_score": confidence_score,
            # Retained so the worker can store grounded embeddings post-sign-off.
            "candidate_facts": candidate_facts or [],
            "evidence_map": evidence_map or {},
        }
        self._save(session_id, payload)
        logger.info(
            "review_queue: staged session %s for physician review (%d discrepancies)",
            session_id, len(discrepancies),
        )
        return payload

    def _save(self, session_id: str, payload: Dict[str, Any]) -> None:
        if self._redis_available:
            try:
                self._redis.set(self._key(session_id), json.dumps(payload), ex=self._TTL_SECONDS)
                return
            except Exception as exc:
                logger.warning("review_queue: Redis write failed (%s), falling back", exc)
        with self._lock:
            self._fallback[session_id] = payload

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self._redis_available:
            try:
                raw = self._redis.get(self._key(session_id))
                if raw:
                    return json.loads(raw)
            except Exception as exc:
                logger.warning("review_queue: Redis read failed (%s), falling back", exc)
        with self._lock:
            return self._fallback.get(session_id)

    def clear(self, session_id: str) -> None:
        if self._redis_available:
            try:
                self._redis.delete(self._key(session_id))
            except Exception:
                pass
        with self._lock:
            self._fallback.pop(session_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

review_queue_store = ReviewQueueStore()
