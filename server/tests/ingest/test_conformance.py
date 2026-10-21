"""
Queue conformance suite (T2 / #92, SDD §2.3.3, §9.8 gate).

Real Postgres, real concurrency: threads with their own connections, or
spawned processes where a worker must be SIGKILLed. Run with
INGEST_TEST_DATABASE_URL set (see conftest.py).
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.ingest import claim as q
from app.ingest.engine import OUTCOME_DONE, OUTCOME_FENCE_REJECTED, Worker
from app.ingest.noop_stage import EXHAUSTED_TOPIC, NoopStage
from app.ingest.outbox import InMemoryOutboxPublisher, write_outbox
from app.ingest.reconciler import Reconciler
from app.ingest.stage import StageRegistry

from . import procs
from .helpers import (
    drain,
    fast_cfg,
    record_commit,
    run_threads,
    scalar,
    seed,
    task_with_token,
    wait_for,
)

pytestmark = pytest.mark.db

SPAWN = mp.get_context("spawn")


def _commits(engine) -> int:
    return int(scalar(engine, "select count(*) from noop_commits"))


def _state(engine, task_id):
    with engine.connect() as conn:
        return conn.execute(
            text("select state, attempts, last_error, lease_token from ingest_tasks where task_id = :t"),
            {"t": task_id},
        ).one()


def _reconciler(engine, cfg, metrics, stages=None, publisher=None, name="r1"):
    return Reconciler(
        engine,
        StageRegistry(stages or [NoopStage()]),
        cfg,
        publisher or InMemoryOutboxPublisher(),
        metrics=metrics,
        name=name,
    )


def _wait_expired(engine, task_id, timeout=15.0):
    wait_for(
        lambda: scalar(
            engine,
            "select lease_expires_at < clock_timestamp() from ingest_tasks where task_id = :t and state = 'leased'",
            t=task_id,
        )
        is True,
        timeout=timeout,
        what=f"lease on task {task_id} to expire",
    )


# 1 --------------------------------------------------------------------


def test_01_no_double_commit_under_concurrency(db, metrics):
    seed(db, 2000, sessions=50)
    cfg = fast_cfg()
    stage = NoopStage(commit_hook=record_commit)
    workers = [Worker(db, stage, cfg, pod=f"pod-{i}", metrics=metrics, heartbeat=False) for i in range(8)]
    errors = run_threads([lambda w=w: drain(w, db, timeout=120) for w in workers], timeout=150)
    assert errors == []
    assert _commits(db) == 2000
    assert scalar(db, "select count(*) from ingest_tasks where state = 'done' and attempts = 1") == 2000
    assert metrics.read("ingest_fence_rejections_total", stage="noop") == 0


# 2 --------------------------------------------------------------------


def test_02_kill_mid_lease_retries_and_commits_once(db, db_url, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()
    p = SPAWN.Process(target=procs.run_noop_worker, args=(db_url, "pod-a", 30.0, 5, 1), daemon=True)
    p.start()
    try:
        wait_for(lambda: _state(db, task_id)[0] == "leased", timeout=30, what="worker to claim")
        time.sleep(1.0)
    finally:
        p.kill()
        p.join(5)
    assert _state(db, task_id)[0] == "leased"
    _wait_expired(db, task_id)
    res = _reconciler(db, cfg, metrics).expire_leases()
    assert res.requeued == 1
    state, attempts, last_error, _ = _state(db, task_id)
    assert (state, attempts, last_error) == ("queued", 1, q.LEASE_EXPIRED_ERROR)

    worker = Worker(db, NoopStage(commit_hook=record_commit), cfg, pod="pod-b", metrics=metrics)
    drain(worker, db, timeout=15)
    assert _state(db, task_id)[:2] == ("done", 2)
    assert _commits(db) == 1


# 3 --------------------------------------------------------------------


def test_03_commit_past_lease_is_fenced(db, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()
    stage = NoopStage(sleep_for=lambda t: 9.0 if t.attempts == 1 else 0.0, commit_hook=record_commit)
    slow = Worker(db, stage, cfg, pod="pod-slow", metrics=metrics, heartbeat=False)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", slow.run_once()), daemon=True)
    t.start()
    wait_for(lambda: _state(db, task_id)[0] == "leased", timeout=10, what="slow worker to claim")
    slow_token = _state(db, task_id)[3]

    _wait_expired(db, task_id)
    assert _reconciler(db, cfg, metrics).expire_leases().requeued == 1
    fast = Worker(db, stage, cfg, pod="pod-fast", metrics=metrics)
    drain(fast, db, timeout=5)
    assert _state(db, task_id)[0] == "done"

    t.join(15)
    assert [r.outcome for r in result["r"]] == [OUTCOME_FENCE_REJECTED]
    assert metrics.read("ingest_fence_rejections_total", stage="noop") == 1
    assert _commits(db) == 1
    assert scalar(db, "select lease_token from noop_commits where task_id = :t", t=task_id) != slow_token


# 4 --------------------------------------------------------------------


def test_04_restart_under_same_pod_name_cannot_commit_stale_work(db, db_url, metrics):
    t1, t2 = seed(db, 2)
    cfg = fast_cfg()
    p = SPAWN.Process(target=procs.run_noop_worker, args=(db_url, "pod-a", 30.0, 5, 1), daemon=True)
    p.start()
    try:
        wait_for(lambda: _state(db, t1)[0] == "leased", timeout=30, what="first pod-a to claim")
        old_token = _state(db, t1)[3]
    finally:
        p.kill()
        p.join(5)

    # The restarted pod has the same name and claims other work first.
    reborn = Worker(db, NoopStage(commit_hook=record_commit), cfg, pod="pod-a", metrics=metrics)
    assert [r.outcome for r in reborn.run_once()] == [OUTCOME_DONE]
    assert _state(db, t2)[0] == "done"

    _wait_expired(db, t1)
    _reconciler(db, cfg, metrics).expire_leases()
    drain(reborn, db, timeout=10)
    assert _state(db, t1)[0] == "done"

    stale = task_with_token(db, t1, old_token)
    with db.begin() as conn:
        assert q.fence(conn, stale) is False
    assert _commits(db) == 2
    assert scalar(db, "select lease_token from noop_commits where task_id = :t", t=t1) != old_token


# 5 --------------------------------------------------------------------


def test_05_renewal_keeps_a_long_task_alive(db, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()
    worker = Worker(db, NoopStage(sleep_seconds=15.0, commit_hook=record_commit), cfg, pod="pod-a", metrics=metrics)
    rec = _reconciler(db, cfg, metrics)
    stop = threading.Event()
    swept = []

    def sweep():
        while not stop.is_set():
            swept.append(rec.expire_leases().requeued)
            stop.wait(0.5)

    sweeper = threading.Thread(target=sweep, daemon=True)
    sweeper.start()
    try:
        assert [r.outcome for r in worker.run_once()] == [OUTCOME_DONE]
    finally:
        stop.set()
        sweeper.join(5)
    assert sum(swept) == 0 and len(swept) >= 20
    assert _state(db, task_id)[:2] == ("done", 1)
    assert metrics.read("ingest_lease_lost_total", stage="noop") == 0
    assert metrics.read("ingest_fence_rejections_total", stage="noop") == 0
    assert _commits(db) == 1


# 6 --------------------------------------------------------------------


def test_06_priority_order_with_aging(db):
    cfg = fast_cfg()  # aging_step 240 s
    groups = {
        "blocking_fresh": seed(db, 3, priority="blocking"),
        "backfill_10m": seed(db, 5, priority="backfill", enqueued_ago_seconds=600),
        "active_5m": seed(db, 5, priority="active", enqueued_ago_seconds=300),
        "active_fresh": seed(db, 5, priority="active"),
        "backfill_fresh": seed(db, 5, priority="backfill"),
    }
    order = []
    for _ in range(23):
        with db.begin() as conn:
            (t,) = q.claim(conn, stage="noop", pod="p", cfg=cfg)
        order.append(t.task_id)
    expected = (
        groups["blocking_fresh"]  # always first, even ahead of 10-minute-old backfill
        + groups["backfill_10m"]  # 2*240 - 600 = -120
        + groups["active_5m"]  # 240 - 300 = -60
        + groups["active_fresh"]  # 240
        + groups["backfill_fresh"]  # 480
    )
    assert order == expected


def test_06b_starvation_bound_under_continuous_active_stream(db, metrics):
    aging = 2
    cfg = fast_cfg(aging_step_seconds=aging)
    stop = threading.Event()

    def top_up():
        while not stop.is_set():
            depth = scalar(db, "select count(*) from ingest_tasks where state = 'queued' and priority = 'active'")
            if depth < 20:
                seed(db, 20 - depth, priority="active", session_prefix="a")
            stop.wait(0.01)

    producer = threading.Thread(target=top_up, daemon=True)
    producer.start()
    wait_for(lambda: scalar(db, "select count(*) from ingest_tasks") >= 20, timeout=5, what="active backlog")
    (backfill_id,) = seed(db, 1, priority="backfill", session_prefix="b")
    t0 = time.monotonic()
    stage = NoopStage(sleep_seconds=0.02)
    workers = [Worker(db, stage, cfg, pod=f"p{i}", metrics=metrics, heartbeat=False) for i in range(2)]

    def work(w):
        while not stop.is_set() and _state(db, backfill_id)[0] == "queued":
            w.run_once()

    errors = run_threads([lambda w=w: work(w) for w in workers], timeout=30)
    waited = time.monotonic() - t0
    stop.set()
    producer.join(5)
    assert errors == []
    assert _state(db, backfill_id)[0] in ("leased", "done")
    # Claimed once it is aging_step older than the newest active work at the head.
    assert waited <= aging + 2.0, f"backfill waited {waited:.2f}s with aging_step={aging}s"


# 7 --------------------------------------------------------------------


def _sample_max_leased(db, session_id, stop, out):
    samples = []
    while not stop.is_set():
        n = scalar(
            db,
            "select count(*) from ingest_tasks where state = 'leased' and stage = 'page' and session_id = :s",
            s=session_id,
        )
        samples.append(int(n))
        stop.wait(0.005)
    busy = [n for n in samples if n > 0] or [0]
    out["peak"] = max(busy)
    out["mean_while_busy"] = sum(busy) / len(busy)


def test_07_per_session_cap_with_documented_overshoot(db, metrics):
    cap, n_workers = 2, 8
    cfg = fast_cfg(page_task_cap=cap)
    seed(db, 100, stage="page", pages=True, session_prefix="big")  # session big0
    seed(db, 50, stage="page", pages=True, sessions=10, session_prefix="small")
    stage = NoopStage(name="page", sleep_seconds=0.05, commit_hook=record_commit)
    workers = [Worker(db, stage, cfg, pod=f"p{i}", metrics=metrics, heartbeat=False) for i in range(n_workers)]
    stop, out = threading.Event(), {}
    sampler = threading.Thread(target=_sample_max_leased, args=(db, "big0", stop, out), daemon=True)
    sampler.start()
    errors = run_threads([lambda w=w: drain(w, db, timeout=120) for w in workers], timeout=150)
    stop.set()
    sampler.join(5)
    assert errors == []
    assert _commits(db) == 150
    # Soft cap: concurrent claimers do not see each other's uncommitted
    # leases, so overshoot is bounded by the number of claimers (§5.2.3.3).
    # The harness reports the observed overshoot; this asserts the bound.
    print(f"cap={cap} workers={n_workers} peak={out['peak']} mean_while_busy={out['mean_while_busy']:.2f}")
    assert out["peak"] <= cap + n_workers
    # Fairness: the big session does not hold the small ones back.
    with db.connect() as conn:
        last_small, last_big = conn.execute(
            text(
                """
                select max(c.committed_at) filter (where t.session_id like 'small%'),
                       max(c.committed_at) filter (where t.session_id = 'big0')
                from noop_commits c join ingest_tasks t using (task_id)
                """
            )
        ).one()
    assert last_small < last_big


def test_07b_blocking_bypasses_cap(db, metrics):
    cap, n_workers = 2, 8
    cfg = fast_cfg(page_task_cap=cap)
    seed(db, 40, stage="page", pages=True, priority="blocking", session_prefix="big")
    stage = NoopStage(name="page", sleep_seconds=0.1)
    workers = [Worker(db, stage, cfg, pod=f"p{i}", metrics=metrics, heartbeat=False) for i in range(n_workers)]
    stop, out = threading.Event(), {}
    sampler = threading.Thread(target=_sample_max_leased, args=(db, "big0", stop, out), daemon=True)
    sampler.start()
    errors = run_threads([lambda w=w: drain(w, db, timeout=60) for w in workers], timeout=90)
    stop.set()
    sampler.join(5)
    assert errors == []
    assert out["peak"] > cap


# 8 --------------------------------------------------------------------


def test_08_bump_to_blocking_takes_effect_on_next_claim(db):
    cfg = fast_cfg()
    seed(db, 3, enqueued_ago_seconds=120)  # older, would lead
    doc = uuid.uuid4()
    with db.begin() as conn:
        target = q.enqueue(conn, doc_id=doc, session_id="s9", stage="noop", priority="active")
    with db.begin() as conn:
        assert q.bump_to_blocking(conn, doc) == 1
        assert q.bump_to_blocking(conn, doc) == 0  # idempotent
    with db.begin() as conn:
        (t,) = q.claim(conn, stage="noop", pod="p", cfg=cfg)
    assert t.task_id == target and t.priority == "blocking"


# 9 --------------------------------------------------------------------


def test_09a_retry_until_success(db, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()
    stage = NoopStage(fail_compute=lambda t: t.attempts < 5, commit_hook=record_commit)
    drain(Worker(db, stage, cfg, pod="p", metrics=metrics), db, timeout=20)
    assert _state(db, task_id)[:2] == ("done", 5)
    assert _commits(db) == 1
    assert metrics.read("ingest_task_retries_total", stage="noop", reason="compute_error") == 4


def test_09b_exhaustion_marks_failed_and_runs_hook_once(db, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()
    stage = NoopStage(fail_compute=lambda t: True, commit_hook=record_commit)
    drain(Worker(db, stage, cfg, pod="p", metrics=metrics), db, timeout=20)
    state, attempts, last_error, token = _state(db, task_id)
    assert (state, attempts, token) == ("failed", 5, None)
    assert last_error.startswith("InjectedFailure: injected compute failure")
    assert _commits(db) == 0
    assert scalar(db, "select count(*) from ingest_outbox where topic = :t", t=EXHAUSTED_TOPIC) == 1
    assert scalar(db, "select (payload->>'task_id')::bigint from ingest_outbox") == task_id
    assert metrics.read("ingest_tasks_failed_total", stage="noop") == 1


# 10 -------------------------------------------------------------------


def test_10_commit_raises_rolls_back_and_retries(db, metrics):
    (task_id,) = seed(db, 1)
    cfg = fast_cfg()

    def hook(conn, task):
        record_commit(conn, task)  # partial output, must be rolled back
        if task.attempts == 1:
            raise RuntimeError("injected commit failure")

    drain(Worker(db, NoopStage(commit_hook=hook), cfg, pod="p", metrics=metrics), db, timeout=10)
    assert _state(db, task_id)[:2] == ("done", 2)
    assert _commits(db) == 1
    assert metrics.read("ingest_task_retries_total", stage="noop", reason="commit_error") == 1


# 11 -------------------------------------------------------------------


def test_11_two_reconcilers_handle_each_expired_lease_once(db, metrics):
    cfg = fast_cfg()
    with db.begin() as conn:
        conn.execute(
            text(
                """
                insert into ingest_tasks (doc_id, session_id, stage, priority, state, attempts,
                                          lease_token, lease_owner, lease_expires_at)
                select gen_random_uuid(), 's' || (i % 7), 'noop', 'active', 'leased',
                       case when i <= 150 then 1 else 5 end,
                       gen_random_uuid(), 'dead-pod', clock_timestamp() - interval '1 minute'
                from generate_series(1, 200) i
                """
            )
        )
    recs = [_reconciler(db, cfg, metrics, name=f"r{i}") for i in range(2)]
    totals = {"requeued": 0, "failed": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def loop(rec):
        barrier.wait()
        for _ in range(20):
            res = rec.expire_leases()
            with lock:
                totals["requeued"] += res.requeued
                totals["failed"] += res.failed
            if scalar(db, "select count(*) from ingest_tasks where state = 'leased'") == 0:
                return

    assert run_threads([lambda r=r: loop(r) for r in recs], timeout=60) == []
    assert totals == {"requeued": 150, "failed": 50}
    assert scalar(db, "select count(*) from ingest_tasks where state = 'queued' and attempts = 1") == 150
    assert scalar(db, "select count(*) from ingest_tasks where state = 'failed'") == 50
    assert scalar(db, "select count(*) from ingest_outbox") == 50
    assert scalar(db, "select count(distinct payload->>'task_id') from ingest_outbox") == 50


# 12 -------------------------------------------------------------------


def test_12_outbox_relay_is_at_least_once(db, metrics, monkeypatch):
    cfg = fast_cfg()
    with db.begin() as conn:
        ids = [write_outbox(conn, topic="t", key=f"k{i}", payload={"n": i}) for i in range(3)]
    pub = InMemoryOutboxPublisher()
    pub.fail_next(ids[1])
    rec = _reconciler(db, cfg, metrics, publisher=pub)

    first = rec.relay_outbox()
    assert (first.sent, first.publish_failures) == (2, 1)
    assert scalar(db, "select sent_at is null from ingest_outbox where event_id = :e", e=str(ids[1])) is True
    assert metrics.read("ingest_outbox_publish_failures_total") == 1
    second = rec.relay_outbox()
    assert (second.sent, second.publish_failures) == (1, 0)
    assert scalar(db, "select count(*) from ingest_outbox where sent_at is null") == 0
    assert sorted(e for *_, e in pub.published) == sorted(ids)

    # Crash between publish and sent_at: the row is published again, same event_id.
    with db.begin() as conn:
        e4 = write_outbox(conn, topic="t", key="k4", payload={"n": 4})
    real_mark = rec._mark_sent
    calls = {"n": 0}

    def flaky_mark(conn, event_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("update ingest_outbox", {}, Exception("injected"))
        real_mark(conn, event_id)

    monkeypatch.setattr(rec, "_mark_sent", flaky_mark)
    assert rec.relay_outbox().aborted is True
    assert scalar(db, "select sent_at is null from ingest_outbox where event_id = :e", e=str(e4)) is True
    rec.relay_outbox()
    assert [e for *_, e in pub.published].count(e4) == 2
    assert scalar(db, "select count(*) from ingest_outbox where sent_at is null") == 0


# 13 -------------------------------------------------------------------


def test_13_partial_unique_indexes_and_checks(db):
    doc = uuid.uuid4()
    with db.begin() as conn:
        assert q.enqueue(conn, doc_id=doc, session_id="s", stage="split", priority="active") is not None
        assert q.enqueue(conn, doc_id=doc, session_id="s", stage="split", priority="active") is None
        assert q.enqueue(conn, doc_id=doc, session_id="s", stage="page", priority="active", page=1) is not None
        assert q.enqueue(conn, doc_id=doc, session_id="s", stage="page", priority="active", page=1) is None
        assert q.enqueue(conn, doc_id=doc, session_id="s", stage="page", priority="active", page=2) is not None
    assert scalar(db, "select count(*) from ingest_tasks") == 3

    cases = [
        ("insert into ingest_tasks (doc_id, session_id, stage, priority, state) "
         "values (:d, 's', 'split', 'active', 'queued')", "ingest_tasks_doc_stage"),
        ("insert into ingest_tasks (doc_id, session_id, stage, page, priority, state) "
         "values (:d, 's', 'page', 1, 'active', 'queued')", "ingest_tasks_page_stage"),
        ("insert into ingest_tasks (doc_id, session_id, stage, priority, state) "
         "values (gen_random_uuid(), 's', 'page', 'active', 'queued')", "ingest_tasks_page_iff_page_stage"),
        ("insert into ingest_tasks (doc_id, session_id, stage, priority, state) "
         "values (gen_random_uuid(), 's', 'noop', 'active', 'leased')", "ingest_tasks_leased_has_lease"),
        ("insert into ingest_tasks (doc_id, session_id, stage, priority, state) "
         "values (gen_random_uuid(), 's', 'noop', 'active', 'running')", "ingest_tasks_state_known"),
    ]
    for sql, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            with db.begin() as conn:
                conn.execute(text(sql), {"d": str(doc)})
