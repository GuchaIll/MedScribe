"""Shared helpers for the ingest queue conformance suite and harness."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Callable, Iterable, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.ingest.claim import ClaimedTask
from app.ingest.config import IngestQueueConfig
from app.ingest.engine import Worker

TEST_DB_ENV = "INGEST_TEST_DATABASE_URL"

NOOP_COMMITS_DDL = """
create table if not exists noop_commits (
  task_id      bigint not null unique,
  lease_token  uuid not null,
  committed_at timestamptz not null default clock_timestamp()
)
"""


def fast_cfg(**overrides) -> IngestQueueConfig:
    """Short lease and backoff so lifecycle cases run in seconds."""
    values = dict(
        lease_seconds=5,
        backoff_base_seconds=0.05,
        backoff_cap_seconds=0.2,
        poll_interval_seconds=0.01,
        idle_poll_interval_seconds=0.05,
    )
    values.update(overrides)
    return IngestQueueConfig.load(values)


def make_engine(url: str, pool_size: int = 4) -> Engine:
    return create_engine(url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True)


def record_commit(conn: Connection, task: ClaimedTask) -> None:
    """Commit hook: a second commit of one task is a unique violation."""
    conn.execute(
        text("insert into noop_commits (task_id, lease_token) values (:t, :k)"),
        {"t": task.task_id, "k": str(task.lease_token)},
    )


def truncate(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(NOOP_COMMITS_DDL))
        conn.execute(text("truncate ingest_tasks, ingest_outbox, noop_commits restart identity"))


def seed(
    engine: Engine,
    n: int,
    *,
    stage: str = "noop",
    priority: str = "active",
    sessions: int = 1,
    session_prefix: str = "s",
    enqueued_ago_seconds: float = 0.0,
    pages: bool = False,
) -> List[int]:
    """Insert n queued tasks spread over `sessions` sessions. Returns task_ids in insert order."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                insert into ingest_tasks (doc_id, session_id, stage, page, priority, state, enqueued_at)
                select gen_random_uuid(),
                       :prefix || ((i - 1) % :sessions)::text,
                       :stage,
                       case when :pages then i else null end,
                       cast(:priority as task_priority),
                       'queued',
                       now() - make_interval(secs => :ago)
                from generate_series(1, :n) as i
                order by i
                returning task_id
                """
            ),
            {
                "prefix": session_prefix,
                "sessions": sessions,
                "stage": stage,
                "pages": pages,
                "priority": priority,
                "ago": enqueued_ago_seconds,
                "n": n,
            },
        ).fetchall()
    return [int(r[0]) for r in rows]


def scalar(engine: Engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def open_tasks(engine: Engine) -> int:
    return int(scalar(engine, "select count(*) from ingest_tasks where state in ('queued', 'leased')"))


def drain(worker: Worker, engine: Engine, *, timeout: float = 60.0, stop: Optional[threading.Event] = None) -> int:
    """Run the worker until no queued or leased task remains. Returns tasks processed."""
    done = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop is not None and stop.is_set():
            return done
        results = worker.run_once()
        done += len(results)
        if not results:
            if open_tasks(engine) == 0:
                return done
            time.sleep(0.01)
    raise TimeoutError(f"queue not drained within {timeout}s; open={open_tasks(engine)}")


def run_threads(targets: Iterable[Callable[[], None]], *, timeout: float = 120.0) -> List[BaseException]:
    """Run callables in threads; return any exceptions they raised."""
    errors: List[BaseException] = []
    lock = threading.Lock()

    def wrap(fn):
        def inner():
            try:
                fn()
            except BaseException as exc:  # surfaced to the test
                with lock:
                    errors.append(exc)

        return inner

    threads = [threading.Thread(target=wrap(fn), daemon=True) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
        if t.is_alive():
            errors.append(TimeoutError(f"thread {t.name} still running after {timeout}s"))
    return errors


def wait_for(predicate: Callable[[], bool], *, timeout: float, interval: float = 0.05, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout}s waiting for {what}")


def task_with_token(engine: Engine, task_id: int, token: uuid.UUID) -> ClaimedTask:
    """Rebuild a ClaimedTask carrying a specific (possibly stale) lease token."""
    with engine.connect() as conn:
        row = conn.execute(
            text("select doc_id, page, session_id, stage, attempts, priority::text from ingest_tasks where task_id = :t"),
            {"t": task_id},
        ).one()
    return ClaimedTask(
        task_id=task_id,
        lease_token=token,
        doc_id=row[0],
        page=row[1],
        session_id=row[2],
        stage=row[3],
        attempts=int(row[4]),
        priority=row[5],
        age_seconds=0.0,
    )


def configured_db_url() -> Optional[str]:
    return os.environ.get(TEST_DB_ENV) or None
