"""
Batch worker engine (SDD §5.2.3.3).

One task:
  1. claim in its own short transaction (C.3)
  2. compute with no transaction open; a heartbeat thread renews every lease/3
  3. output transaction: bound the lock hold, fence first (C.4), stage
     before_commit + commit, commit
  4. compute or commit raised: requeue with backoff, or mark failed and run
     stage.on_exhausted, in one token-guarded transaction

Lease lost (renew returned zero rows) or fence rejected: write nothing. The
reconciler owns the task from there.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.logging import get_logger

from . import claim as q
from .claim import ClaimedTask
from .config import IngestQueueConfig
from .errors import FenceRejectedError, IngestInputError, LeaseLostError
from .metrics import IngestMetrics, default_metrics
from .stage import Stage, validate_stage

logger = get_logger(__name__)

OUTCOME_DONE = "done"
OUTCOME_RETRIED = "retried"
OUTCOME_FAILED = "failed"
OUTCOME_LEASE_LOST = "lease_lost"
OUTCOME_FENCE_REJECTED = "fence_rejected"
OUTCOME_ABANDONED = "abandoned"  # retry/exhaust found the lease already gone


@dataclass(frozen=True)
class TaskResult:
    """Outcome of one task, returned by run_once for tests and the harness."""

    task_id: int
    outcome: str


class _Heartbeat:
    """Renews one task's lease every interval on its own connection."""

    def __init__(
        self,
        engine: Engine,
        task: ClaimedTask,
        lease_seconds: int,
        interval: float,
        metrics: IngestMetrics,
    ) -> None:
        self._engine = engine
        self._task = task
        self._lease = lease_seconds
        self._interval = interval
        self._metrics = metrics
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"ingest-heartbeat-{task.task_id}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 5)

    def _run(self) -> None:
        last_ok = time.monotonic()
        while not self._stop.wait(self._interval):
            try:
                with self._engine.begin() as conn:
                    ok = q.renew(conn, self._task, self._lease)
            except SQLAlchemyError as exc:
                # Cannot reach the DB. The local clock only decides when to give
                # up; correctness still rests on the fence.
                if time.monotonic() - last_ok >= self._lease:
                    self._mark_lost(f"renew failing for a full lease ({type(exc).__name__})")
                    return
                logger.warning(
                    "lease renew failed, will retry task_id=%s stage=%s error=%s",
                    self._task.task_id,
                    self._task.stage,
                    type(exc).__name__,
                )
                continue
            if not ok:
                self._mark_lost("renew returned zero rows")
                return
            last_ok = time.monotonic()

    def _mark_lost(self, why: str) -> None:
        self.lost.set()
        self._metrics.lease_lost(self._task.stage)
        err = LeaseLostError(self._task.task_id, self._task.stage)
        logger.warning(
            "%s (%s); output will be discarded session_id=%s doc_id=%s attempts=%s",
            err,
            why,
            self._task.session_id,
            self._task.doc_id,
            self._task.attempts,
        )


class Worker:
    """Runs one stage: poll, claim, compute, fence, commit."""

    def __init__(
        self,
        engine: Engine,
        stage: Stage,
        cfg: IngestQueueConfig,
        *,
        pod: str,
        metrics: Optional[IngestMetrics] = None,
        heartbeat: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if engine is None:
            raise IngestInputError("engine", engine, "a SQLAlchemy Engine")
        if not isinstance(cfg, IngestQueueConfig):
            raise IngestInputError("cfg", type(cfg).__name__, "an IngestQueueConfig")
        if not isinstance(pod, str) or not pod.strip():
            raise IngestInputError("pod", pod, "a non-empty pod name")
        self.engine = engine
        self.stage = validate_stage(stage)
        self.cfg = cfg
        self.pod = pod
        self.metrics = metrics or default_metrics()
        # heartbeat=False exists for the commit-past-lease conformance case.
        self.heartbeat = heartbeat
        self._sleep = sleep
        self.lease_seconds = stage.lease_seconds or cfg.lease_seconds

    # -- polling ---------------------------------------------------------

    def run_forever(self, stop: threading.Event) -> None:
        logger.info(
            "ingest worker started pod=%s stage=%s lease_seconds=%s batch=%s",
            self.pod,
            self.stage.name,
            self.lease_seconds,
            self.cfg.batch,
        )
        empty = 0
        while not stop.is_set():
            try:
                results = self.run_once()
            except SQLAlchemyError as exc:
                logger.warning(
                    "claim failed, retrying next poll pod=%s stage=%s error=%s",
                    self.pod,
                    self.stage.name,
                    type(exc).__name__,
                )
                results = []
            if results:
                empty = 0
                continue
            empty += 1
            interval = (
                self.cfg.idle_poll_interval_seconds
                if empty >= self.cfg.idle_polls_before_backoff
                else self.cfg.poll_interval_seconds
            )
            stop.wait(interval)
        logger.info("ingest worker stopped pod=%s stage=%s", self.pod, self.stage.name)

    def run_once(self) -> List[TaskResult]:
        """Claim up to batch tasks and process each. Empty list = nothing claimable."""
        with self.engine.begin() as conn:
            tasks = q.claim(conn, stage=self.stage.name, pod=self.pod, cfg=self.cfg, lease_seconds=self.lease_seconds)
        if not tasks:
            logger.debug("no claimable task pod=%s stage=%s", self.pod, self.stage.name)
            return []
        return [self.process(t) for t in tasks]

    # -- one task --------------------------------------------------------

    def process(self, task: ClaimedTask) -> TaskResult:
        self.metrics.claimed(task.stage, task.priority, task.age_seconds)
        logger.info(
            "task claimed task_id=%s stage=%s session_id=%s doc_id=%s page=%s attempts=%s priority=%s pod=%s",
            task.task_id,
            task.stage,
            task.session_id,
            task.doc_id,
            task.page,
            task.attempts,
            task.priority,
            self.pod,
        )
        started = time.monotonic()
        hb: Optional[_Heartbeat] = None
        if self.heartbeat:
            hb = _Heartbeat(self.engine, task, self.lease_seconds, self.cfg.renew_interval_seconds, self.metrics)
            hb.start()
        try:
            output = self.stage.compute(task)
        except Exception as exc:  # stage code: any failure is a retry
            if hb is not None:
                hb.stop()
            if hb is not None and hb.lost.is_set():
                return TaskResult(task.task_id, OUTCOME_LEASE_LOST)
            logger.warning(
                "compute raised task_id=%s stage=%s attempts=%s error=%s",
                task.task_id,
                task.stage,
                task.attempts,
                type(exc).__name__,
                exc_info=True,
            )
            return self._fail_attempt(task, exc, reason="compute_error")
        if hb is not None:
            hb.stop()
            if hb.lost.is_set():
                return TaskResult(task.task_id, OUTCOME_LEASE_LOST)

        try:
            self._commit_output(task, output)
        except FenceRejectedError as exc:
            self.metrics.fence_rejected(task.stage)
            logger.warning(
                "%s; rolled back, wrote nothing session_id=%s doc_id=%s attempts=%s",
                exc,
                task.session_id,
                task.doc_id,
                task.attempts,
            )
            return TaskResult(task.task_id, OUTCOME_FENCE_REJECTED)
        except Exception as exc:  # stage.commit or the DB; transaction already rolled back
            logger.warning(
                "output transaction failed, rolled back task_id=%s stage=%s attempts=%s error=%s",
                task.task_id,
                task.stage,
                task.attempts,
                type(exc).__name__,
                exc_info=True,
            )
            return self._fail_attempt(task, exc, reason="commit_error")
        logger.info(
            "task done task_id=%s stage=%s attempts=%s duration_ms=%d",
            task.task_id,
            task.stage,
            task.attempts,
            (time.monotonic() - started) * 1000,
        )
        return TaskResult(task.task_id, OUTCOME_DONE)

    def _bound_lock_hold(self, conn: Connection) -> None:
        # Postgres 15: no transaction_timeout, so bound each statement and idle gaps.
        conn.execute(
            text(
                "select set_config('statement_timeout', :st, true), "
                "set_config('idle_in_transaction_session_timeout', :idle, true)"
            ),
            {"st": str(self.cfg.output_statement_timeout_ms), "idle": str(self.cfg.output_idle_in_tx_timeout_ms)},
        )

    def _commit_output(self, task: ClaimedTask, output: Any) -> None:
        with self.engine.connect() as conn:
            with conn.begin():
                self._bound_lock_hold(conn)
                if not q.fence(conn, task):
                    raise FenceRejectedError(task.task_id, task.stage)
                self.stage.before_commit(conn, task)
                self.stage.commit(conn, task, output)

    def _fail_attempt(self, task: ClaimedTask, exc: BaseException, *, reason: str) -> TaskResult:
        error = q.format_error(exc)
        try:
            with self.engine.begin() as conn:
                if task.attempts >= self.cfg.max_attempts:
                    if not q.mark_failed(conn, task, error=error):
                        return self._abandoned(task, reason)
                    self.stage.on_exhausted(conn, task, error)
                    exhausted = True
                else:
                    delay = q.backoff_seconds(task.attempts, self.cfg)
                    if not q.requeue(conn, task, error=error, delay_seconds=delay):
                        return self._abandoned(task, reason)
                    exhausted = False
        except SQLAlchemyError as db_exc:
            logger.error(
                "could not record failed attempt; reconciler will expire the lease task_id=%s stage=%s error=%s",
                task.task_id,
                task.stage,
                type(db_exc).__name__,
            )
            return TaskResult(task.task_id, OUTCOME_ABANDONED)
        except Exception:
            logger.exception(
                "on_exhausted raised; task stays leased until the reconciler retries exhaustion task_id=%s stage=%s",
                task.task_id,
                task.stage,
            )
            return TaskResult(task.task_id, OUTCOME_ABANDONED)
        if exhausted:
            self.metrics.failed(task.stage)
            logger.error(
                "task failed at max attempts task_id=%s stage=%s session_id=%s doc_id=%s attempts=%s reason=%s",
                task.task_id,
                task.stage,
                task.session_id,
                task.doc_id,
                task.attempts,
                reason,
            )
            return TaskResult(task.task_id, OUTCOME_FAILED)
        self.metrics.retried(task.stage, reason)
        logger.warning(
            "task requeued with backoff task_id=%s stage=%s attempts=%s reason=%s",
            task.task_id,
            task.stage,
            task.attempts,
            reason,
        )
        return TaskResult(task.task_id, OUTCOME_RETRIED)

    def _abandoned(self, task: ClaimedTask, reason: str) -> TaskResult:
        logger.warning(
            "lease already gone when recording failure; wrote nothing task_id=%s stage=%s attempts=%s reason=%s",
            task.task_id,
            task.stage,
            task.attempts,
            reason,
        )
        return TaskResult(task.task_id, OUTCOME_ABANDONED)


__all__ = [
    "Worker",
    "TaskResult",
    "OUTCOME_DONE",
    "OUTCOME_RETRIED",
    "OUTCOME_FAILED",
    "OUTCOME_LEASE_LOST",
    "OUTCOME_FENCE_REJECTED",
    "OUTCOME_ABANDONED",
]
