"""
Queue statements: claim, renew, fence, retry/exhaust, enqueue, bump.

SQL follows SDD Appendix C.3 / C.4. Every deadline is computed by Postgres
from `clock_timestamp()`; Python only supplies interval lengths. Callers own
the transaction: each function runs on the connection it is given and never
commits.

Deviations from C.3, all deliberate:
- `returning` also gives session_id, stage, attempts, priority and age
  (logging, registry lookup, backoff, claim metrics) so the engine never
  re-reads the row.
- `blocking` sorts strictly first. With the C.3 formula alone, a backfill
  task older than 2 * aging_step outranks a fresh blocking task, which
  contradicts "blocking always leads" (§5.2.3.3). Aging still orders
  active against backfill.
- The per-session cap applies to the `page` stage only (§5.2.3.3 "at most
  $cap leased page tasks"); other stages pass cap=None.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import IngestQueueConfig
from .errors import IngestInputError

PRIORITIES = ("blocking", "active", "backfill")
PAGE_STAGE = "page"
MAX_ERROR_CHARS = 2000
LEASE_EXPIRED_ERROR = "lease_expired"


@dataclass(frozen=True)
class ClaimedTask:
    """What a claim returns. Read by the engine, the stage, and the reconciler."""

    task_id: int  # renew, fence, retry update
    lease_token: uuid.UUID  # renew, fence, retry update
    doc_id: uuid.UUID  # stage.compute
    page: Optional[int]  # stage.compute
    session_id: str  # log context, metric labels
    stage: str  # registry lookup
    attempts: int  # backoff, exhaustion
    priority: str  # ingest_claims_total{priority}
    age_seconds: float  # ingest_task_age_seconds (claim time minus enqueued_at)


_CLAIM_SQL = text(
    """
    with busy as (
      select session_id, count(*) as n
      from ingest_tasks
      where state = 'leased' and stage = :stage
      group by session_id
    ),
    picked as (
      select t.task_id
      from ingest_tasks t
      left join busy b using (session_id)
      where t.stage = :stage
        and t.state = 'queued'
        and t.not_before <= now()
        and (t.priority = 'blocking'
             or cast(:cap as int) is null
             or coalesce(b.n, 0) < cast(:cap as int))
      order by (t.priority <> 'blocking'),
               (array_position(enum_range(null::task_priority), t.priority) - 1) * :aging_step
               - extract(epoch from now() - t.enqueued_at),
               t.task_id
      for update of t skip locked
      limit :batch
    )
    update ingest_tasks t
    set state = 'leased',
        lease_token = gen_random_uuid(),
        lease_owner = :pod,
        lease_expires_at = clock_timestamp() + make_interval(secs => :lease),
        attempts = attempts + 1
    from picked
    where t.task_id = picked.task_id
    returning t.task_id, t.lease_token, t.doc_id, t.page, t.session_id, t.stage, t.attempts,
              t.priority::text as priority,
              extract(epoch from clock_timestamp() - t.enqueued_at)::float8 as age_seconds
    """
)

_RENEW_SQL = text(
    """
    update ingest_tasks set lease_expires_at = clock_timestamp() + make_interval(secs => :lease)
    where task_id = :task_id and lease_token = :token and state = 'leased'
      and lease_expires_at > clock_timestamp()
    returning task_id
    """
)

_FENCE_SQL = text(
    """
    update ingest_tasks
       set state = 'done', lease_token = null, lease_expires_at = null
     where task_id = :task_id and lease_token = :token and state = 'leased'
       and lease_expires_at > clock_timestamp()
    returning task_id
    """
)

# Retry/exhaust after a failed attempt. Guarded by token, not by expiry: the
# attempt is still ours until someone else re-claims it (new token) or the
# reconciler moves it (state changes). Row lock serializes with the sweep.
_RETRY_SQL = text(
    """
    update ingest_tasks
       set state = 'queued', lease_token = null, lease_expires_at = null,
           not_before = clock_timestamp() + make_interval(secs => :delay),
           last_error = :error
     where task_id = :task_id and lease_token = :token and state = 'leased'
    returning task_id
    """
)

_EXHAUST_SQL = text(
    """
    update ingest_tasks
       set state = 'failed', lease_token = null, lease_expires_at = null,
           last_error = :error
     where task_id = :task_id and lease_token = :token and state = 'leased'
    returning task_id
    """
)

_ENQUEUE_DOC_SQL = text(
    """
    insert into ingest_tasks (doc_id, session_id, stage, page, priority, state)
    values (:doc_id, :session_id, :stage, null, cast(:priority as task_priority), 'queued')
    on conflict (doc_id, stage) where page is null do nothing
    returning task_id
    """
)

_ENQUEUE_PAGE_SQL = text(
    """
    insert into ingest_tasks (doc_id, session_id, stage, page, priority, state)
    values (:doc_id, :session_id, :stage, :page, cast(:priority as task_priority), 'queued')
    on conflict (doc_id, stage, page) where page is not null do nothing
    returning task_id
    """
)

_BUMP_SQL = text(
    """
    update ingest_tasks set priority = 'blocking'
    where doc_id = :doc_id and state = 'queued' and priority <> 'blocking'
    """
)


def row_to_task(row) -> ClaimedTask:
    return ClaimedTask(
        task_id=int(row.task_id),
        lease_token=row.lease_token if isinstance(row.lease_token, uuid.UUID) else uuid.UUID(str(row.lease_token)),
        doc_id=row.doc_id if isinstance(row.doc_id, uuid.UUID) else uuid.UUID(str(row.doc_id)),
        page=row.page,
        session_id=row.session_id,
        stage=row.stage,
        attempts=int(row.attempts),
        priority=row.priority,
        age_seconds=float(row.age_seconds),
    )


def _require_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestInputError(field, value, "a non-empty string")
    return value


def claim(
    conn: Connection,
    *,
    stage: str,
    pod: str,
    cfg: IngestQueueConfig,
    lease_seconds: Optional[int] = None,
) -> List[ClaimedTask]:
    """One-statement claim (C.3). Returns up to cfg.batch leased tasks."""
    _require_text("stage", stage)
    _require_text("pod", pod)
    lease = lease_seconds if lease_seconds is not None else cfg.lease_seconds
    rows = conn.execute(
        _CLAIM_SQL,
        {
            "stage": stage,
            "cap": cfg.page_task_cap if stage == PAGE_STAGE else None,
            "aging_step": cfg.aging_step_seconds,
            "batch": cfg.batch,
            "pod": pod,
            "lease": lease,
        },
    ).fetchall()
    return [row_to_task(r) for r in rows]


def renew(conn: Connection, task: ClaimedTask, lease_seconds: int) -> bool:
    """Extend the lease (C.4). False means the lease is gone: abandon, write nothing."""
    row = conn.execute(
        _RENEW_SQL, {"task_id": task.task_id, "token": str(task.lease_token), "lease": lease_seconds}
    ).first()
    return row is not None


def fence(conn: Connection, task: ClaimedTask) -> bool:
    """
    Must be the first data statement of the output transaction (C.4).

    Marks the task done and locks its row. False means roll back and write nothing.
    """
    row = conn.execute(_FENCE_SQL, {"task_id": task.task_id, "token": str(task.lease_token)}).first()
    return row is not None


def backoff_seconds(attempts: int, cfg: IngestQueueConfig, rng: Optional[random.Random] = None) -> float:
    """min(base * 2^(attempts-1), cap) with +/- jitter; attempts counts claims (>= 1)."""
    if not isinstance(attempts, int) or attempts < 1:
        raise IngestInputError("attempts", attempts, "an int >= 1")
    base = min(cfg.backoff_base_seconds * (2 ** min(attempts - 1, 30)), cfg.backoff_cap_seconds)
    r = rng.random() if rng is not None else random.random()
    return max(0.0, base * (1.0 + cfg.backoff_jitter * (2.0 * r - 1.0)))


def format_error(exc: BaseException) -> str:
    """Exception class and message, truncated. Callers must not pass payload text in messages."""
    msg = f"{type(exc).__name__}: {exc}"
    return msg[:MAX_ERROR_CHARS]


def requeue(conn: Connection, task: ClaimedTask, *, error: str, delay_seconds: float) -> bool:
    """Back to queued with backoff. False: our lease is no longer on the row."""
    row = conn.execute(
        _RETRY_SQL,
        {
            "task_id": task.task_id,
            "token": str(task.lease_token),
            "delay": float(delay_seconds),
            "error": error[:MAX_ERROR_CHARS],
        },
    ).first()
    return row is not None


def mark_failed(conn: Connection, task: ClaimedTask, *, error: str) -> bool:
    """Terminal failure. Caller runs stage.on_exhausted in the same transaction."""
    row = conn.execute(
        _EXHAUST_SQL, {"task_id": task.task_id, "token": str(task.lease_token), "error": error[:MAX_ERROR_CHARS]}
    ).first()
    return row is not None


def enqueue(
    conn: Connection,
    *,
    doc_id: uuid.UUID,
    session_id: str,
    stage: str,
    priority: str,
    page: Optional[int] = None,
) -> Optional[int]:
    """Idempotent insert. Returns the new task_id, or None if the task already exists."""
    if not isinstance(doc_id, uuid.UUID):
        raise IngestInputError("doc_id", doc_id, "a uuid.UUID")
    _require_text("session_id", session_id)
    _require_text("stage", stage)
    if priority not in PRIORITIES:
        raise IngestInputError("priority", priority, f"one of {PRIORITIES}")
    if stage == PAGE_STAGE:
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise IngestInputError("page", page, "a non-negative int for stage 'page'")
    elif page is not None:
        raise IngestInputError("page", page, f"None for stage {stage!r} (only 'page' carries a page)")
    params = {"doc_id": str(doc_id), "session_id": session_id, "stage": stage, "priority": priority}
    if page is None:
        row = conn.execute(_ENQUEUE_DOC_SQL, params).first()
    else:
        row = conn.execute(_ENQUEUE_PAGE_SQL, {**params, "page": page}).first()
    return int(row.task_id) if row is not None else None


def bump_to_blocking(conn: Connection, doc_id: uuid.UUID) -> int:
    """Raise a document's queued tasks to blocking; the next claim honors it. Returns rows changed."""
    if not isinstance(doc_id, uuid.UUID):
        raise IngestInputError("doc_id", doc_id, "a uuid.UUID")
    return conn.execute(_BUMP_SQL, {"doc_id": str(doc_id)}).rowcount


__all__ = [
    "ClaimedTask",
    "PRIORITIES",
    "PAGE_STAGE",
    "LEASE_EXPIRED_ERROR",
    "claim",
    "renew",
    "fence",
    "requeue",
    "mark_failed",
    "backoff_seconds",
    "format_error",
    "enqueue",
    "bump_to_blocking",
]
