"""
Ingest queue baseline (T2 / #92): throughput, claim latency, churn,
starvation bound, and per-session cap overshoot, all on the no-op stage.

Needs a disposable, migrated Postgres. Truncates the queue tables.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import random
import statistics
import threading
import time
from typing import List

from app.ingest import claim as q
from app.ingest.engine import Worker
from app.ingest.metrics import IngestMetrics
from app.ingest.noop_stage import NoopStage
from app.ingest.outbox import InMemoryOutboxPublisher
from app.ingest.reconciler import Reconciler
from app.ingest.stage import StageRegistry
from tests.ingest.helpers import fast_cfg, make_engine, open_tasks, record_commit, scalar, seed, truncate

from ..report import Report, Row

TITLE = "Ingest queue (T2, no-op stage)"
SPAWN = mp.get_context("spawn")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-url", required=True, help="disposable, migrated Postgres")
    parser.add_argument("--tasks", type=int, default=4000, help="tasks per throughput run")
    parser.add_argument("--churn-seconds", type=int, default=120)
    parser.add_argument("--churn-kill-every", type=float, default=10.0)


def _pct(xs: List[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else 0.0


# -- worker process ------------------------------------------------------


def _worker_proc(url: str, pod: str, sleep_seconds: float, until_empty: bool, out) -> None:
    import logging

    logging.getLogger("app.ingest").setLevel(logging.WARNING)
    engine = make_engine(url, pool_size=2)
    latencies: List[float] = []
    real_claim = q.claim

    def timed_claim(*a, **k):
        t = time.perf_counter()
        try:
            return real_claim(*a, **k)
        finally:
            latencies.append((time.perf_counter() - t) * 1000)

    q.claim = timed_claim  # the engine calls q.claim through the module
    w = Worker(engine, NoopStage(sleep_seconds=sleep_seconds, commit_hook=record_commit), fast_cfg(), pod=pod,
               metrics=IngestMetrics(registry=_registry()))
    done = 0
    while True:
        res = w.run_once()
        done += len(res)
        if not res:
            if until_empty and open_tasks(engine) == 0:
                break
            time.sleep(0.005)
    out.put({"pod": pod, "done": done, "latencies": latencies})


def _registry():
    from prometheus_client import CollectorRegistry

    return CollectorRegistry()


# -- scenarios -----------------------------------------------------------


def throughput(url: str, engine, n_tasks: int, workers: int) -> List[Row]:
    truncate(engine)
    seed(engine, n_tasks, sessions=50)
    out = SPAWN.Queue()
    procs = [SPAWN.Process(target=_worker_proc, args=(url, f"w{i}", 0.0, True, out)) for i in range(workers)]
    t0 = time.monotonic()
    for p in procs:
        p.start()
    results = [out.get(timeout=600) for _ in procs]
    elapsed = time.monotonic() - t0
    for p in procs:
        p.join(10)
    lat = [x for r in results for x in r["latencies"]]
    commits = int(scalar(engine, "select count(*) from noop_commits"))
    name = f"throughput, {workers} worker{'s' if workers > 1 else ''}"
    return [
        Row(name, "tasks committed", commits, "tasks", f"of {n_tasks}; a duplicate would be a unique violation"),
        Row(name, "throughput", commits / elapsed, "tasks/s", "includes process start-up"),
        Row(name, "claim latency p50", _pct(lat, 0.5), "ms", "one claim transaction, including empty polls"),
        Row(name, "claim latency p95", _pct(lat, 0.95), "ms", ""),
    ]


def churn(url: str, engine, seconds: int, kill_every: float) -> List[Row]:
    truncate(engine)
    workers, sleep_s = 8, 0.2
    seed(engine, int(seconds / sleep_s * workers * 1.2), sessions=50)
    cfg = fast_cfg()
    metrics = IngestMetrics(registry=_registry())
    rec = Reconciler(engine, StageRegistry([NoopStage()]), cfg, InMemoryOutboxPublisher(), metrics=metrics)
    stop = threading.Event()
    rec_thread = threading.Thread(target=rec.run_forever, args=(stop,), daemon=True)
    rec_thread.start()
    out = SPAWN.Queue()
    procs = {i: SPAWN.Process(target=_worker_proc, args=(url, f"w{i}", sleep_s, False, out)) for i in range(workers)}
    for p in procs.values():
        p.start()
    kills = 0
    rng = random.Random(92)
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        time.sleep(kill_every)
        i = rng.randrange(workers)
        procs[i].kill()
        procs[i].join(5)
        kills += 1
        procs[i] = SPAWN.Process(target=_worker_proc, args=(url, f"w{i}-r{kills}", sleep_s, False, out))
        procs[i].start()
    for p in procs.values():
        p.kill()
        p.join(5)
    # Let the reconciler re-queue what the final kill left leased, then stop.
    time.sleep(cfg.lease_seconds + 6)
    stop.set()
    rec_thread.join(10)
    commits = int(scalar(engine, "select count(*) from noop_commits"))
    retried = int(scalar(engine, "select count(*) from ingest_tasks where last_error = 'lease_expired'"))
    name = f"churn: 8 workers, one SIGKILL every {kill_every:.0f} s for {seconds} s"
    return [
        Row(name, "worker kills", kills, "kills", ""),
        Row(name, "tasks committed", commits, "tasks", "noop_commits is unique per task: no double commit"),
        Row(name, "tasks re-queued by lease expiry", retried, "tasks",
            "about one in-flight task per kill, plus the 8 killed at the end. SIGKILL churn shows up here, not as fence "
            "rejections: a killed worker never reaches its fence (commit-past-lease is conformance case 3)"),
        Row(name, "tasks still leased after expiry sweep",
            int(scalar(engine, "select count(*) from ingest_tasks where state = 'leased'")), "tasks", "should be 0"),
    ]


def starvation(engine, aging: int = 2) -> List[Row]:
    truncate(engine)
    cfg = fast_cfg(aging_step_seconds=aging)
    stop = threading.Event()

    def top_up():
        while not stop.is_set():
            depth = scalar(engine, "select count(*) from ingest_tasks where state = 'queued' and priority = 'active'")
            if depth < 20:
                seed(engine, 20 - depth, priority="active", session_prefix="a")
            stop.wait(0.01)

    producer = threading.Thread(target=top_up, daemon=True)
    producer.start()
    time.sleep(0.5)
    waits = []
    stage = NoopStage(sleep_seconds=0.02)
    ws = [Worker(engine, stage, cfg, pod=f"p{i}", metrics=IngestMetrics(registry=_registry()), heartbeat=False)
          for i in range(2)]
    for _ in range(3):
        (bid,) = seed(engine, 1, priority="backfill", session_prefix="b")
        t0 = time.monotonic()
        state = {"v": "queued"}

        def work(w):
            while state["v"] == "queued":
                w.run_once()
                state["v"] = scalar(engine, "select state from ingest_tasks where task_id = :t", t=bid)

        ts = [threading.Thread(target=work, args=(w,)) for w in ws]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        waits.append(time.monotonic() - t0)
    stop.set()
    producer.join(5)
    name = f"starvation: backfill behind a continuous active stream (aging_step = {aging} s)"
    return [
        Row(name, "backfill wait, max of 3", max(waits), "s", f"bound is about aging_step ({aging} s) plus drain lag"),
        Row(name, "backfill wait, mean of 3", statistics.mean(waits), "s", "scales linearly with aging_step (240 s default)"),
    ]


def cap_overshoot(engine, cap: int, workers: int = 8) -> List[Row]:
    truncate(engine)
    cfg = fast_cfg(page_task_cap=cap)
    seed(engine, 200, stage="page", pages=True, session_prefix="big")
    seed(engine, 100, stage="page", pages=True, sessions=10, session_prefix="small")
    stage = NoopStage(name="page", sleep_seconds=0.05)
    ws = [Worker(engine, stage, cfg, pod=f"p{i}", metrics=IngestMetrics(registry=_registry()), heartbeat=False)
          for i in range(workers)]
    stop = threading.Event()
    samples: List[int] = []

    def sample():
        while not stop.is_set():
            samples.append(int(scalar(engine, "select count(*) from ingest_tasks where state = 'leased' "
                                              "and stage = 'page' and session_id = 'big0'")))
            stop.wait(0.005)

    def work(w):
        while open_tasks(engine):
            if not w.run_once():
                time.sleep(0.005)

    s = threading.Thread(target=sample, daemon=True)
    s.start()
    ts = [threading.Thread(target=work, args=(w,)) for w in ws]
    for t in ts:
        t.start()
    for t in ts:
        t.join(300)
    stop.set()
    s.join(5)
    busy = [n for n in samples if n > 0] or [0]
    name = f"per-session cap = {cap}, {workers} workers, 50 ms tasks"
    return [
        Row(name, "peak leased (big session)", max(busy), "tasks", f"documented bound cap + workers = {cap + workers}"),
        Row(name, "p95 leased (big session)", _pct(busy, 0.95), "tasks", ""),
        Row(name, "mean leased while busy", statistics.mean(busy), "tasks", "time-averaged over 5 ms samples"),
    ]


def run(args: argparse.Namespace) -> Report:
    engine = make_engine(args.db_url, pool_size=24)
    rows: List[Row] = []
    for n in (1, 4, 8):
        rows += throughput(args.db_url, engine, args.tasks, n)
    rows += churn(args.db_url, engine, args.churn_seconds, args.churn_kill_every)
    rows += starvation(engine)
    for cap in (2, 4):
        rows += cap_overshoot(engine, cap)
    truncate(engine)
    engine.dispose()
    return Report(
        suite="ingest_queue",
        rows=rows,
        params={"tasks": args.tasks, "lease_seconds": 5, "postgres": scalar(make_engine(args.db_url, 1), "show server_version")},
    )
