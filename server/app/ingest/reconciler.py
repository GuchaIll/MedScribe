"""
Reconciler loops for the ingest queue (SDD §5.2.3.6, T2 subset).

- lease expiry (5 s): expired leases -> queued with backoff, or failed plus
  stage.on_exhausted at max attempts, in one transaction per task
- outbox relay (1 s): unsent rows -> publisher, then sent_at (at-least-once)
- repair (60 s): queue-internal invariant checks, logged at warning, never
  auto-fixed

Every sweep is `for update skip locked`, so two replicas share the work with
no leader election. Progress fan-out, Lease sharding, stats, retention and
orphan GC arrive with #93 / #94.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.logging import get_logger

from . import claim as q

from .config import IngestQueueConfig
from .errors import IngestInputError
from .metrics import IngestMetrics, default_metrics
from .outbox import OutboxPublisher
from .stage import StageRegistry

logger = get_logger(__name__)

SWEEP_LIMIT = 100
OUTBOX_STALE_SECONDS = 300
STUCK_LEASE_FACTOR = 10

LEASE_EXPIRY_INTERVAL = 5.0
OUTBOX_RELAY_INTERVAL = 1.0
REPAIR_INTERVAL = 60.0

_EXPIRED_SQL = text(
    """
    select task_id, lease_token, doc_id, page, session_id, stage, attempts,
           priority::text as priority, lease_owner,
           extract(epoch from clock_timestamp() - enqueued_at)::float8 as age_seconds
    from ingest_tasks
    where state = 'leased' and lease_expires_at < clock_timestamp()
    order by lease_expires_at
    for update skip locked
    limit :limit
    """
)

_UNSENT_SQL = text(
    """
    select event_id, topic, key, payload
    from ingest_outbox
    where sent_at is null
    order by created_at
    for update skip locked
    limit :limit
    """
)

_MARK_SENT_SQL = text("update ingest_outbox set sent_at = clock_timestamp() where event_id = :event_id")

_OLDEST_UNSENT_SQL = text(
    """
    select coalesce(extract(epoch from clock_timestamp() - min(created_at)), 0)::float8
    from ingest_outbox where sent_at is null
    """
)

_DEPTH_SQL = text(
    """
    select stage, priority::text, count(*) from ingest_tasks
    where state = 'queued' group by stage, priority
    """
)

_REPAIR_QUEUED_EXHAUSTED_SQL = text(
    """
    select task_id from ingest_tasks
    where state = 'queued' and attempts >= :max_attempts
    order by task_id limit 20
    """
)

_REPAIR_STUCK_LEASE_SQL = text(
    """
    select task_id, lease_owner from ingest_tasks
    where state = 'leased'
      and lease_expires_at < clock_timestamp() - make_interval(secs => :stuck)
    order by task_id limit 20
    """
)

_REPAIR_STALE_OUTBOX_SQL = text(
    """
    select count(*) from ingest_outbox
    where sent_at is null and created_at < clock_timestamp() - make_interval(secs => :stale)
    """
)


@dataclass
class ExpiryResult:
    requeued: int = 0
    failed: int = 0
    skipped_unknown_stage: int = 0
    errors: int = 0


@dataclass
class RelayResult:
    sent: int = 0
    publish_failures: int = 0
    aborted: bool = False


@dataclass
class RepairResult:
    queued_exhausted: List[int] = field(default_factory=list)
    stuck_leases: List[int] = field(default_factory=list)
    stale_outbox: int = 0


class Reconciler:
    def __init__(
        self,
        engine: Engine,
        registry: StageRegistry,
        cfg: IngestQueueConfig,
        publisher: OutboxPublisher,
        *,
        metrics: IngestMetrics | None = None,
        name: str = "reconciler",
    ) -> None:
        if engine is None:
            raise IngestInputError("engine", engine, "a SQLAlchemy Engine")
        if not isinstance(registry, StageRegistry):
            raise IngestInputError("registry", type(registry).__name__, "a StageRegistry")
        if not isinstance(cfg, IngestQueueConfig):
            raise IngestInputError("cfg", type(cfg).__name__, "an IngestQueueConfig")
        if publisher is None or not callable(getattr(publisher, "publish", None)):
            raise IngestInputError("publisher", publisher, "an OutboxPublisher")
        self.engine = engine
        self.registry = registry
        self.cfg = cfg
        self.publisher = publisher
        self.metrics = metrics or default_metrics()
        self.name = name

    # -- lease expiry ----------------------------------------------------

    def expire_leases(self) -> ExpiryResult:
        res = ExpiryResult()
        with self.engine.connect() as conn:
            with conn.begin():
                rows = conn.execute(_EXPIRED_SQL, {"limit": SWEEP_LIMIT}).fetchall()
                for row in rows:
                    self._expire_one(conn, row, res)
        if rows:
            logger.info(
                "lease expiry sweep reconciler=%s requeued=%d failed=%d skipped=%d errors=%d",
                self.name,
                res.requeued,
                res.failed,
                res.skipped_unknown_stage,
                res.errors,
            )
        return res

    def _expire_one(self, conn: Connection, row, res: ExpiryResult) -> None:
        task = q.row_to_task(row)
        if task.stage not in self.registry:
            # Without the stage we cannot run its terminal transition, so leave
            # the row for a reconciler that has it; repair keeps reporting it.
            res.skipped_unknown_stage += 1
            logger.error(
                "expired lease for a stage this reconciler does not know; left leased task_id=%s stage=%s registered=%s",
                task.task_id,
                task.stage,
                self.registry.names(),
            )
            return
        sp = conn.begin_nested()
        try:
            if task.attempts >= self.cfg.max_attempts:
                q.mark_failed(conn, task, error=q.LEASE_EXPIRED_ERROR)
                self.registry.get(task.stage).on_exhausted(conn, task, q.LEASE_EXPIRED_ERROR)
                sp.commit()
                res.failed += 1
                self.metrics.failed(task.stage)
                logger.error(
                    "expired lease at max attempts, task failed task_id=%s stage=%s lease_owner=%s attempts=%s",
                    task.task_id,
                    task.stage,
                    row.lease_owner,
                    task.attempts,
                )
            else:
                delay = q.backoff_seconds(task.attempts, self.cfg)
                q.requeue(conn, task, error=q.LEASE_EXPIRED_ERROR, delay_seconds=delay)
                sp.commit()
                res.requeued += 1
                self.metrics.retried(task.stage, q.LEASE_EXPIRED_ERROR)
                logger.warning(
                    "expired lease requeued task_id=%s stage=%s lease_owner=%s attempts=%s delay_s=%.2f",
                    task.task_id,
                    task.stage,
                    row.lease_owner,
                    task.attempts,
                    delay,
                )
        except Exception:
            sp.rollback()
            res.errors += 1
            logger.exception(
                "lease expiry failed for one task, left for the next sweep task_id=%s stage=%s",
                task.task_id,
                task.stage,
            )

    # -- outbox relay ----------------------------------------------------

    def _mark_sent(self, conn: Connection, event_id: uuid.UUID) -> None:
        conn.execute(_MARK_SENT_SQL, {"event_id": str(event_id)})

    def relay_outbox(self) -> RelayResult:
        res = RelayResult()
        try:
            with self.engine.connect() as conn:
                with conn.begin():
                    rows = conn.execute(_UNSENT_SQL, {"limit": SWEEP_LIMIT}).fetchall()
                    for row in rows:
                        event_id = row.event_id if isinstance(row.event_id, uuid.UUID) else uuid.UUID(str(row.event_id))
                        try:
                            self.publisher.publish(
                                topic=row.topic, key=row.key, payload=dict(row.payload), event_id=event_id
                            )
                        except Exception as exc:
                            res.publish_failures += 1
                            self.metrics.outbox_publish_failed()
                            logger.warning(
                                "outbox publish failed, will retry next tick event_id=%s topic=%s error=%s",
                                event_id,
                                row.topic,
                                type(exc).__name__,
                            )
                            continue
                        self._mark_sent(conn, event_id)
                        res.sent += 1
        except SQLAlchemyError as exc:
            # Rows published in this batch are re-sent next tick (at-least-once).
            res.aborted = True
            logger.warning(
                "outbox relay batch rolled back; published rows will be re-sent reconciler=%s published=%d error=%s",
                self.name,
                res.sent,
                type(exc).__name__,
            )
        self._sample_outbox_age()
        if res.sent or res.publish_failures:
            logger.info(
                "outbox relay reconciler=%s sent=%d failures=%d", self.name, res.sent, res.publish_failures
            )
        return res

    def _sample_outbox_age(self) -> None:
        try:
            with self.engine.connect() as conn:
                age = conn.execute(_OLDEST_UNSENT_SQL).scalar_one()
            self.metrics.outbox_oldest_unsent(float(age))
        except SQLAlchemyError as exc:
            logger.warning("could not sample outbox age error=%s", type(exc).__name__)

    # -- queue depth -----------------------------------------------------

    def sample_queue_depth(self) -> Dict[tuple, int]:
        with self.engine.connect() as conn:
            rows = [(r[0], r[1], int(r[2])) for r in conn.execute(_DEPTH_SQL)]
        self.metrics.set_queue_depth(rows)
        return {(s, p): n for s, p, n in rows}

    # -- repair ----------------------------------------------------------

    def repair(self) -> RepairResult:
        res = RepairResult()
        with self.engine.connect() as conn:
            res.queued_exhausted = [
                int(r[0]) for r in conn.execute(_REPAIR_QUEUED_EXHAUSTED_SQL, {"max_attempts": self.cfg.max_attempts})
            ]
            stuck = conn.execute(
                _REPAIR_STUCK_LEASE_SQL, {"stuck": self.cfg.lease_seconds * STUCK_LEASE_FACTOR}
            ).fetchall()
            res.stuck_leases = [int(r[0]) for r in stuck]
            res.stale_outbox = int(
                conn.execute(_REPAIR_STALE_OUTBOX_SQL, {"stale": OUTBOX_STALE_SECONDS}).scalar_one()
            )
        if res.queued_exhausted:
            logger.warning(
                "repair: queued tasks at or past max_attempts (should be failed) count=%d task_ids=%s",
                len(res.queued_exhausted),
                res.queued_exhausted,
            )
        if stuck:
            logger.warning(
                "repair: leases expired more than %dx lease ago (expiry loop stuck?) count=%d task_ids=%s owners=%s",
                STUCK_LEASE_FACTOR,
                len(stuck),
                res.stuck_leases,
                sorted({r[1] for r in stuck if r[1]}),
            )
        if res.stale_outbox:
            logger.warning(
                "repair: outbox rows unsent for more than %ds count=%d", OUTBOX_STALE_SECONDS, res.stale_outbox
            )
        return res

    # -- scheduling ------------------------------------------------------

    def run_forever(self, stop: threading.Event) -> None:
        loops: List[tuple[str, float, Callable[[], object]]] = [
            ("lease_expiry", LEASE_EXPIRY_INTERVAL, self._expiry_tick),
            ("outbox_relay", OUTBOX_RELAY_INTERVAL, self.relay_outbox),
            ("repair", REPAIR_INTERVAL, self.repair),
        ]
        next_run = {name: 0.0 for name, _, _ in loops}
        logger.info("reconciler started name=%s", self.name)
        while not stop.is_set():
            now = time.monotonic()
            for name, interval, fn in loops:
                if now < next_run[name]:
                    continue
                next_run[name] = now + interval
                try:
                    fn()
                except Exception:
                    logger.exception("reconciler loop failed, will retry next interval loop=%s name=%s", name, self.name)
            stop.wait(max(0.05, min(next_run.values()) - time.monotonic()))
        logger.info("reconciler stopped name=%s", self.name)

    def _expiry_tick(self) -> None:
        self.expire_leases()
        self.sample_queue_depth()


__all__ = ["Reconciler", "ExpiryResult", "RelayResult", "RepairResult"]
