"""
Patient context snapshot — load once per session (agent refactor Phase 1A, #51).

Plan §6: prior patient state is loaded once per session (and on patient switch),
cached under the session key, and reused by the assist path, Lane B, the safety
tools, and the default scopes of the retrieve_* tools. A full DB reload as graph
node 2 on every compile is exactly what this replaces.

The snapshot holds *materialized prior state*. What else has been received but
not yet materialized is the receipt ledger's job (§20.3, #84), not this one.

Invalidation (§6.2): OCR field approval, clinician edits to meds or allergies,
external record sync, TTL expiry, end-session reconcile, and ingest_delta
completing for a document that touches labs or problems.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)

# Reasons a snapshot may be dropped (plan §6.2). Anything outside this set is a
# caller mistake, not a new policy.
INVALIDATION_REASONS = (
    "ocr_field_approved",
    "clinician_edit",
    "external_record_sync",
    "ttl_expired",
    "end_session_reconcile",
    "ingest_delta_completed",
    "patient_switch",
    "manual",
)

DEFAULT_TTL_SECONDS = 3600


class PatientContextSnapshot(TypedDict):
    """Materialized prior state for one patient, cached per session (§6.1).

    Facts are stored once, grouped by fact type, exactly as the embedding store
    groups them. §6.1's named sections (allergies, medications, problems,
    recent labs) are views over that one copy — see ``snapshot_sections`` — so
    there is never a second, drifting copy of the same clinical fact.
    """

    patient_id: str
    tenant_id: Optional[str]
    version: int
    demographics: Dict[str, Any]
    facts_by_type: Dict[str, List[Dict[str, Any]]]
    prior_record: Dict[str, Any]
    recent_visits_index: List[Dict[str, Any]]
    retrieval_keys: Dict[str, Any]
    visit_count: int
    loaded_at: str
    loaded_from_db: bool
    source: str                      # "db" | "cache" | "empty"


# Section name -> fact types that feed it, most specific first. Section names
# are the ones §6.1 and get_patient_profile use; fact types are what the
# embedding store emits.
SECTION_FACT_TYPES: Dict[str, tuple] = {
    "allergies": ("allergy", "allergies"),
    "medications": ("medication", "medications"),
    "problems": ("problem", "problems", "diagnosis", "diagnoses"),
    "recent_labs_summary": ("lab_result", "lab", "labs"),
}

# How many rows a section view returns before it stops being a summary.
SECTION_LIMIT = 50
RECENT_LABS_LIMIT = 20


def snapshot_sections(
    snapshot: "PatientContextSnapshot",
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return §6.1 sections as views over the snapshot's single fact copy."""
    wanted = names or (["demographics"] + list(SECTION_FACT_TYPES) + ["recent_visits_index"])
    sections: Dict[str, Any] = {}
    for name in wanted:
        if name == "demographics":
            sections[name] = snapshot["demographics"]
        elif name == "recent_visits_index":
            sections[name] = snapshot["recent_visits_index"]
        elif name in SECTION_FACT_TYPES:
            limit = RECENT_LABS_LIMIT if name == "recent_labs_summary" else SECTION_LIMIT
            sections[name] = _section_rows(snapshot, name)[:limit]
        else:
            raise ValueError(
                f"unknown snapshot section {name!r}; expected any of "
                f"{['demographics', *SECTION_FACT_TYPES, 'recent_visits_index']}"
            )
    return sections


def _section_rows(snapshot: "PatientContextSnapshot", name: str) -> List[Dict[str, Any]]:
    """Rows for one section: indexed facts first, then the finalized record."""
    facts = snapshot["facts_by_type"]
    for fact_type in SECTION_FACT_TYPES[name]:
        rows = facts.get(fact_type)
        if rows:
            return [row for row in rows if isinstance(row, dict)]
    for key in SECTION_FACT_TYPES[name]:
        rows = snapshot["prior_record"].get(key)
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]
    return []


def empty_snapshot(patient_id: str, tenant_id: Optional[str] = None) -> PatientContextSnapshot:
    """A snapshot with no prior state. Callers must not treat this as 'no patient'."""
    return PatientContextSnapshot(
        patient_id=patient_id,
        tenant_id=tenant_id,
        version=0,
        demographics={},
        facts_by_type={},
        prior_record={},
        recent_visits_index=[],
        retrieval_keys={},
        visit_count=0,
        loaded_at=_utcnow_iso(),
        loaded_from_db=False,
        source="empty",
    )


class SnapshotStore:
    """Redis-backed snapshot cache, keyed by session and patient.

    Falls back to an in-process dict when Redis is unavailable, so local runs
    and tests work without it. Connection pattern matches
    ``core/review_queue.py`` so there is one way to reach Redis in this repo.
    """

    _KEY_PREFIX = "session:snapshot:"

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        self.ttl_seconds = ttl_seconds
        self._fallback: Dict[str, PatientContextSnapshot] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._redis_available = False
        self._connect_redis()

    def _connect_redis(self) -> None:
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            logger.info("session_snapshot: REDIS_URL not set, using in-memory fallback")
            return
        try:
            import redis as _redis

            self._redis = _redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._redis_available = True
            logger.info("session_snapshot: connected to Redis")
        except Exception as exc:
            logger.warning(
                "session_snapshot: Redis unavailable (%s), using in-memory fallback", exc
            )
            self._redis = None
            self._redis_available = False

    def _key(self, session_id: str, patient_id: str) -> str:
        return f"{self._KEY_PREFIX}{session_id}:{patient_id}"

    def get(self, session_id: str, patient_id: str) -> Optional[PatientContextSnapshot]:
        """Return the cached snapshot, or None on a miss or an unreadable entry."""
        key = self._key(session_id, patient_id)
        if self._redis_available:
            try:
                raw = self._redis.get(key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as exc:
                logger.warning(
                    "session_snapshot: Redis read failed (%s), falling back to memory", exc
                )
        with self._lock:
            return self._fallback.get(key)

    def put(self, session_id: str, snapshot: PatientContextSnapshot) -> None:
        key = self._key(session_id, snapshot["patient_id"])
        if self._redis_available:
            try:
                self._redis.set(key, json.dumps(snapshot), ex=self.ttl_seconds)
                return
            except Exception as exc:
                logger.warning(
                    "session_snapshot: Redis write failed (%s), falling back to memory", exc
                )
        with self._lock:
            self._fallback[key] = snapshot

    def invalidate(self, session_id: str, patient_id: str, reason: str) -> bool:
        """Drop the cached snapshot. Returns True when something was removed."""
        if reason not in INVALIDATION_REASONS:
            raise ValueError(
                f"unknown invalidation reason {reason!r}; expected one of {list(INVALIDATION_REASONS)}"
            )
        key = self._key(session_id, patient_id)
        removed = False
        if self._redis_available:
            try:
                removed = bool(self._redis.delete(key))
            except Exception as exc:
                logger.warning("session_snapshot: Redis delete failed (%s)", exc)
        with self._lock:
            removed = bool(self._fallback.pop(key, None)) or removed
        logger.info(
            "session_snapshot invalidated: session_id=%s reason=%s removed=%s",
            session_id, reason, removed,
        )
        return removed

    def clear(self) -> None:
        """Drop the in-process cache. Tests use this; production relies on TTL."""
        with self._lock:
            self._fallback.clear()


_store: Optional[SnapshotStore] = None
_store_lock = threading.Lock()


def get_snapshot_store() -> SnapshotStore:
    """Process-wide snapshot store."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SnapshotStore(
                    ttl_seconds=int(
                        os.environ.get("SESSION_SNAPSHOT_TTL_SECONDS", DEFAULT_TTL_SECONDS)
                    )
                )
    return _store


def invalidate_snapshot(
    session_id: str,
    patient_id: str,
    reason: str,
    *,
    store: Optional[SnapshotStore] = None,
) -> bool:
    """Invalidate one session's snapshot for a §6.2 reason."""
    return (store or get_snapshot_store()).invalidate(session_id, patient_id, reason)


def load_snapshot(
    session_id: str,
    patient_id: str,
    ctx: Optional[Any] = None,
    *,
    tenant_id: Optional[str] = None,
    force_reload: bool = False,
    store: Optional[SnapshotStore] = None,
) -> PatientContextSnapshot:
    """Return the session's patient snapshot, loading it from the DB on a miss.

    A cached snapshot comes back with ``source="cache"``; that is the cache hit
    the second compile in a session is supposed to get. A load that finds no
    patient data returns an empty snapshot rather than raising, so the pipeline
    degrades the same way it did before the snapshot existed.
    """
    if not session_id or not isinstance(session_id, str):
        raise ValueError(f"session_id must be a non-empty string, got {session_id!r}")
    if not patient_id or not isinstance(patient_id, str):
        raise ValueError(f"patient_id must be a non-empty string, got {patient_id!r}")

    store = store or get_snapshot_store()

    if not force_reload:
        cached = store.get(session_id, patient_id)
        if cached is not None:
            if cached.get("patient_id") != patient_id:
                # Patient switched on this session key: never serve the old one.
                logger.warning(
                    "session_snapshot: cached patient mismatch on session_id=%s, reloading",
                    session_id,
                )
                store.invalidate(session_id, cached.get("patient_id", ""), "patient_switch")
            else:
                hit = dict(cached)
                hit["source"] = "cache"
                logger.debug(
                    "session_snapshot cache hit: session_id=%s version=%s",
                    session_id, hit.get("version"),
                )
                return hit  # type: ignore[return-value]

    snapshot = _load_from_db(patient_id, ctx, tenant_id)
    store.put(session_id, snapshot)
    return snapshot


def _load_from_db(
    patient_id: str,
    ctx: Optional[Any],
    tenant_id: Optional[str],
) -> PatientContextSnapshot:
    """Build a snapshot from the repositories on an AgentContext.

    Each source is optional and independently guarded: a missing repository or a
    failing query degrades that section only, and the degradation is logged.
    """
    snapshot = empty_snapshot(patient_id, tenant_id)
    if ctx is None:
        logger.warning(
            "session_snapshot: no AgentContext for patient_id=%s; returning empty snapshot",
            patient_id,
        )
        return snapshot

    version = 0
    facts: Dict[str, List[Dict[str, Any]]] = {}

    patient_repo = getattr(ctx, "patient_repo", None)
    if patient_repo is not None:
        try:
            patient = patient_repo.get_by_id(patient_id)
            if patient is not None:
                snapshot["demographics"] = {
                    "full_name": patient.full_name,
                    "dob": patient.dob.isoformat() if patient.dob else None,
                    "age": patient.age,
                    "sex": patient.sex,
                    "mrn": patient.mrn,
                }
            else:
                logger.info("session_snapshot: patient_id=%s not found (new patient)", patient_id)
        except Exception:
            logger.exception("session_snapshot: demographics load failed for patient_id=%s", patient_id)

    record_repo = getattr(ctx, "record_repo", None)
    prior_record: Dict[str, Any] = {}
    if record_repo is not None:
        try:
            records = record_repo.get_for_patient(patient_id, limit=1)
            if records:
                latest = records[0]
                prior_record = latest.structured_data or {}
                version = int(getattr(latest, "version", 0) or 0)
                snapshot["visit_count"] = record_repo.count_for_patient(patient_id)
                snapshot["retrieval_keys"]["latest_record_id"] = str(latest.id)
        except Exception:
            logger.exception("session_snapshot: record load failed for patient_id=%s", patient_id)

    embedding_service = getattr(ctx, "embedding_service", None)
    if embedding_service is not None:
        try:
            facts = embedding_service.get_all_patient_facts(
                patient_id=patient_id, only_final=True
            ) or {}
        except Exception:
            logger.exception("session_snapshot: fact load failed for patient_id=%s", patient_id)

    snapshot["facts_by_type"] = {
        fact_type: [row for row in rows if isinstance(row, dict)]
        for fact_type, rows in facts.items()
        if isinstance(rows, list)
    }
    snapshot["prior_record"] = prior_record
    snapshot["recent_visits_index"] = _visits_index(prior_record, snapshot["visit_count"])
    snapshot["retrieval_keys"]["fact_types"] = sorted(facts)
    snapshot["version"] = version
    snapshot["loaded_at"] = _utcnow_iso()
    snapshot["loaded_from_db"] = bool(
        snapshot["demographics"] or prior_record or facts
    )
    snapshot["source"] = "db" if snapshot["loaded_from_db"] else "empty"

    logger.info(
        "session_snapshot loaded: patient_id=%s version=%s from_db=%s "
        "fact_types=%d facts=%d visits=%d",
        patient_id, version, snapshot["loaded_from_db"], len(snapshot["facts_by_type"]),
        sum(len(rows) for rows in snapshot["facts_by_type"].values()), snapshot["visit_count"],
    )
    return snapshot


def _visits_index(prior_record: Dict[str, Any], visit_count: int) -> List[Dict[str, Any]]:
    """Minimal visit index: enough for retrieve_visits scoping, no note bodies."""
    if not prior_record:
        return []
    return [{
        "record_id": prior_record.get("record_id"),
        "date": prior_record.get("visit_date") or prior_record.get("date"),
        "chief_complaint": prior_record.get("chief_complaint"),
        "is_latest": True,
        "visit_count": visit_count,
    }]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "INVALIDATION_REASONS",
    "RECENT_LABS_LIMIT",
    "SECTION_FACT_TYPES",
    "SECTION_LIMIT",
    "snapshot_sections",
    "PatientContextSnapshot",
    "SnapshotStore",
    "empty_snapshot",
    "get_snapshot_store",
    "invalidate_snapshot",
    "load_snapshot",
]
