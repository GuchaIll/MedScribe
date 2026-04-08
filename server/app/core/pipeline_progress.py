"""
Pipeline progress tracking -- Redis-backed store.

Each session gets a PipelineProgress record that is updated
as the LangGraph workflow streams node-level events.  The
Go API gateway reads the same Redis key via
GET /session/{id}/pipeline/status so the React frontend can
poll for real-time progress regardless of which process is running.

Falls back to in-memory storage when Redis is unavailable (local dev).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node catalogue -- single source of truth for labels + phases
# ---------------------------------------------------------------------------

NodeStatus = Literal["pending", "running", "completed", "failed", "skipped"]

# (name, human-readable label, phase, short description shown to clinician)
PIPELINE_NODE_DEFS: List[tuple] = [
    ("greeting",               "Initialising session",             "ingestion",   "Loading session context and greeting"),
    ("load_patient_context",   "Loading patient history",          "ingestion",   "Retrieving prior visits, medications, allergies from database"),
    ("ingest",                 "Ingesting transcript",             "ingestion",   "Loading raw transcript segments into pipeline state"),
    ("clean_transcription",    "Cleaning transcription",           "ingestion",   "Removing disfluencies, hesitations, and noise"),
    ("normalize_transcript",   "Normalising speaker labels",       "ingestion",   "Standardising speaker labels and timestamps"),
    ("segment_and_chunk",      "Chunking into clinical segments",  "ingestion",   "Splitting conversation into topical clinical chunks"),
    ("extract_candidates",     "Extracting clinical entities",     "extraction",  "NLP extraction of medications, diagnoses, vitals, ICD-10"),
    ("retrieve_evidence",      "Grounding evidence (pgvector)",    "extraction",  "Anchoring each fact to its source utterance via semantic search"),
    ("fill_structured_record", "Compiling structured record",      "extraction",  "Mapping extracted facts to the typed StructuredRecord schema"),
    ("clinical_suggestions",   "Checking drug interactions",       "validation",  "Cross-checking allergies and drug-drug interactions"),
    ("validate_and_score",     "Validating & confidence scoring",  "validation",  "Pydantic validation, per-field confidence scoring, flag assignment"),
    ("repair",                 "Repairing schema errors",          "validation",  "LLM-guided repair of schema validation failures (max 3 attempts)"),
    ("conflict_resolution",    "Resolving clinical conflicts",     "validation",  "Resolving contradictions between new and historical facts"),
    ("human_review_gate",      "Awaiting physician review",        "validation",  "Paused — physician sign-off required before write"),
    ("generate_note",          "Generating SOAP note",             "output",      "LLM generating structured SOAP clinical note from record"),
    ("package_outputs",        "Packaging outputs",                "output",      "Assembling final artifacts for storage and display"),
    ("persist_results",        "Persisting to database",           "output",      "Writing record, embeddings, and audit trace to PostgreSQL"),
]

# Quick lookup: name → index in the ordered list
_NODE_ORDER: Dict[str, int] = {name: i for i, (name, *_) in enumerate(PIPELINE_NODE_DEFS)}

# Simple linear "predicted next" map (best-effort for running indicator)
_PREDICTED_NEXT: Dict[str, Optional[str]] = {
    defs[0]: PIPELINE_NODE_DEFS[i + 1][0] if i + 1 < len(PIPELINE_NODE_DEFS) else None
    for i, defs in enumerate(PIPELINE_NODE_DEFS)
}
# Exceptions — conditional back-edges
_PREDICTED_NEXT["repair"] = "validate_and_score"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NodeProgress:
    name: str
    label: str
    phase: str
    description: str
    status: NodeStatus = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    detail: Optional[str] = None  # "2 medications extracted", "1 conflict resolved"


@dataclass
class PipelineProgress:
    session_id: str
    status: Literal["idle", "running", "completed", "failed"] = "idle"
    current_node: Optional[str] = None
    nodes: List[NodeProgress] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "current_node": self.current_node,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "nodes": [
                {
                    "name": n.name,
                    "label": n.label,
                    "phase": n.phase,
                    "description": n.description,
                    "status": n.status,
                    "started_at": n.started_at,
                    "completed_at": n.completed_at,
                    "duration_ms": n.duration_ms,
                    "detail": n.detail,
                }
                for n in self.nodes
            ],
        }


# ---------------------------------------------------------------------------
# Thread-safe store
# ---------------------------------------------------------------------------

class PipelineProgressStore:
    """
    Redis-backed store keyed by session_id. Compatible with the Go API
    gateway which reads the same ``pipeline:progress:{session_id}`` key.

    Falls back to an in-memory dict when Redis is unavailable so that
    local development without Redis still works.
    """

    # Redis key prefix. The Go gateway reads ``pipeline:{session_id}`` for
    # top-level status (pending/running/completed/failed). This store writes
    # the detailed per-node progress to a separate key so both coexist.
    _KEY_PREFIX = "pipeline:progress:"
    _TTL_SECONDS = 86400  # 24 hours

    def __init__(self) -> None:
        self._fallback: Dict[str, PipelineProgress] = {}
        self._lock = threading.Lock()
        self._node_start_times: Dict[str, float] = {}
        self._redis = None
        self._redis_available = False
        self._connect_redis()

    def _connect_redis(self) -> None:
        """Best-effort Redis connection at startup."""
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            logger.info("pipeline_progress: REDIS_URL not set, using in-memory fallback")
            return
        try:
            import redis as _redis
            self._redis = _redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._redis_available = True
            logger.info("pipeline_progress: connected to Redis at %s", redis_url)
        except Exception as exc:
            logger.warning("pipeline_progress: Redis unavailable (%s), using in-memory fallback", exc)
            self._redis = None
            self._redis_available = False

    def _key(self, session_id: str) -> str:
        return f"{self._KEY_PREFIX}{session_id}"

    def _save(self, session_id: str, progress: PipelineProgress) -> None:
        """Persist progress to Redis (or fallback dict)."""
        if self._redis_available:
            try:
                self._redis.set(
                    self._key(session_id),
                    json.dumps(progress.to_dict()),
                    ex=self._TTL_SECONDS,
                )
                return
            except Exception as exc:
                logger.warning("pipeline_progress: Redis write failed (%s), falling back", exc)
        with self._lock:
            self._fallback[session_id] = progress

    def _load(self, session_id: str) -> Optional[PipelineProgress]:
        """Load progress from Redis (or fallback dict)."""
        if self._redis_available:
            try:
                raw = self._redis.get(self._key(session_id))
                if raw:
                    return self._from_dict(json.loads(raw), session_id)
            except Exception as exc:
                logger.warning("pipeline_progress: Redis read failed (%s), falling back", exc)
        with self._lock:
            return self._fallback.get(session_id)

    @staticmethod
    def _from_dict(data: dict, session_id: str) -> PipelineProgress:
        """Reconstruct a PipelineProgress from its serialised form."""
        nodes = [
            NodeProgress(
                name=n["name"],
                label=n["label"],
                phase=n["phase"],
                description=n.get("description", ""),
                status=n.get("status", "pending"),
                started_at=n.get("started_at"),
                completed_at=n.get("completed_at"),
                duration_ms=n.get("duration_ms"),
                detail=n.get("detail"),
            )
            for n in data.get("nodes", [])
        ]
        return PipelineProgress(
            session_id=session_id,
            status=data.get("status", "idle"),
            current_node=data.get("current_node"),
            nodes=nodes,
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
        )

    # -- Lifecycle -----------------------------------------------------------

    def init_pipeline(self, session_id: str) -> PipelineProgress:
        """Create or reset progress for a session and mark the first node running."""
        nodes = [
            NodeProgress(name=name, label=label, phase=phase, description=desc)
            for name, label, phase, desc in PIPELINE_NODE_DEFS
        ]
        progress = PipelineProgress(
            session_id=session_id,
            status="running",
            started_at=datetime.now().isoformat(),
            nodes=nodes,
        )
        self._node_start_times.clear()
        self._save(session_id, progress)
        self.mark_node_running(session_id, PIPELINE_NODE_DEFS[0][0])
        return progress

    def mark_node_running(self, session_id: str, node_name: str) -> None:
        progress = self._load(session_id)
        if not progress:
            return
        progress.current_node = node_name
        self._node_start_times[f"{session_id}:{node_name}"] = time.monotonic()
        for n in progress.nodes:
            if n.name == node_name and n.status == "pending":
                n.status = "running"
                n.started_at = datetime.now().isoformat()
        self._save(session_id, progress)

    def mark_node_completed(
        self,
        session_id: str,
        node_name: str,
        detail: Optional[str] = None,
    ) -> None:
        progress = self._load(session_id)
        if not progress:
            return
        key = f"{session_id}:{node_name}"
        elapsed_ms = None
        if key in self._node_start_times:
            elapsed_ms = (time.monotonic() - self._node_start_times.pop(key)) * 1000
        for n in progress.nodes:
            if n.name == node_name:
                n.status = "completed"
                n.completed_at = datetime.now().isoformat()
                n.duration_ms = round(elapsed_ms, 1) if elapsed_ms else None
                if detail:
                    n.detail = detail
                break
        self._save(session_id, progress)

        # Optimistically mark the predicted next node as running
        next_node = _PREDICTED_NEXT.get(node_name)
        if next_node:
            self.mark_node_running(session_id, next_node)

    def mark_node_skipped(self, session_id: str, node_name: str) -> None:
        progress = self._load(session_id)
        if not progress:
            return
        for n in progress.nodes:
            if n.name == node_name and n.status == "pending":
                n.status = "skipped"
        self._save(session_id, progress)

    def mark_pipeline_completed(self, session_id: str) -> None:
        progress = self._load(session_id)
        if not progress:
            return
        progress.status = "completed"
        progress.current_node = None
        progress.completed_at = datetime.now().isoformat()
        for n in progress.nodes:
            if n.status in ("pending", "running"):
                n.status = "skipped"
        self._save(session_id, progress)

        # Also update the top-level pipeline:{session_id} key that the Go
        # gateway reads for GET /session/{id}/pipeline/status.
        self._update_go_status_key(session_id, "completed")

    def mark_pipeline_failed(self, session_id: str, error: str) -> None:
        progress = self._load(session_id)
        if not progress:
            return
        progress.status = "failed"
        progress.error = error
        progress.completed_at = datetime.now().isoformat()
        for n in progress.nodes:
            if n.status == "running":
                n.status = "failed"
                n.detail = error[:120]
        self._save(session_id, progress)

        self._update_go_status_key(session_id, "failed", error=error)

    def _update_go_status_key(self, session_id: str, status: str, error: str = "") -> None:
        """
        Write the top-level ``pipeline:{session_id}`` key that the Go gateway's
        GetPipelineStatus reads. This bridges the Python progress store with
        the Go polling endpoint.
        """
        if not self._redis_available:
            return
        try:
            go_key = f"pipeline:{session_id}"
            existing_raw = self._redis.get(go_key)
            go_status = json.loads(existing_raw) if existing_raw else {}
            go_status["status"] = status
            go_status["session_id"] = session_id
            if status in ("completed", "failed"):
                go_status["completed_at_ms"] = int(time.time() * 1000)
            if error:
                go_status["error"] = error
            self._redis.set(go_key, json.dumps(go_status), ex=self._TTL_SECONDS)
        except Exception as exc:
            logger.warning("pipeline_progress: failed to update Go status key: %s", exc)

    # -- Read ----------------------------------------------------------------

    def get(self, session_id: str) -> Optional[PipelineProgress]:
        return self._load(session_id)

    def get_dict(self, session_id: str) -> Optional[dict]:
        progress = self._load(session_id)
        return progress.to_dict() if progress else None

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

pipeline_progress_store = PipelineProgressStore()
