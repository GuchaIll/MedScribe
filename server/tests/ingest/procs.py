"""Process entry points for cases that SIGKILL a worker (spawned, not forked)."""

from __future__ import annotations

import time


def run_noop_worker(url: str, pod: str, sleep_seconds: float, lease_seconds: int, max_tasks: int) -> None:
    from app.ingest.engine import Worker
    from app.ingest.metrics import IngestMetrics
    from app.ingest.noop_stage import NoopStage

    from tests.ingest.helpers import fast_cfg, make_engine, record_commit

    engine = make_engine(url, pool_size=2)
    cfg = fast_cfg(lease_seconds=lease_seconds)
    worker = Worker(
        engine,
        NoopStage(sleep_seconds=sleep_seconds, commit_hook=record_commit),
        cfg,
        pod=pod,
        metrics=IngestMetrics(registry=_registry()),
    )
    processed = 0
    while processed < max_tasks:
        results = worker.run_once()
        processed += len(results)
        if not results:
            time.sleep(0.01)


def _registry():
    from prometheus_client import CollectorRegistry

    return CollectorRegistry()
