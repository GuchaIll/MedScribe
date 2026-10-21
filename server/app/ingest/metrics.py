"""
Ingest queue metrics (SDD D.4 names).

prometheus_client is optional, as in app.agents.tracing.sinks: when it is
missing every method is a no-op and a warning is logged once.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from app.logging import get_logger

logger = get_logger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore[import-untyped]

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

_AGE_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800)


class IngestMetrics:
    """All ingest queue metrics. Pass a registry in tests to read values back."""

    def __init__(self, registry: Optional[Any] = None) -> None:
        self.enabled = _PROMETHEUS_AVAILABLE
        self._depth_labels: Set[Tuple[str, str]] = set()
        if not self.enabled:
            logger.warning("prometheus_client not installed; ingest metrics are no-ops")
            return
        kw: Dict[str, Any] = {"registry": registry} if registry is not None else {}
        self.registry = registry
        self.queue_depth = Gauge("ingest_queue_depth", "Queued tasks", ["stage", "priority"], **kw)
        self.task_age_seconds = Histogram(
            "ingest_task_age_seconds", "Claim time minus enqueued_at", ["stage"], buckets=_AGE_BUCKETS, **kw
        )
        self.claims_total = Counter("ingest_claims_total", "Tasks claimed", ["stage", "priority"], **kw)
        self.task_retries_total = Counter(
            "ingest_task_retries_total", "Attempts that ended in a retry", ["stage", "reason"], **kw
        )
        self.tasks_failed_total = Counter(
            "ingest_tasks_failed_total", "Tasks marked failed at max attempts", ["stage"], **kw
        )
        self.fence_rejections_total = Counter(
            "ingest_fence_rejections_total", "Output transactions rejected by the fence", ["stage"], **kw
        )
        self.lease_lost_total = Counter(
            "ingest_lease_lost_total", "Renewals that found the lease gone", ["stage"], **kw
        )
        self.outbox_publish_failures_total = Counter(
            "ingest_outbox_publish_failures_total", "Outbox rows whose publish raised", **kw
        )
        self.outbox_oldest_unsent_seconds = Gauge(
            "ingest_outbox_oldest_unsent_seconds", "Age of the oldest unsent outbox row (0 if none)", **kw
        )

    def claimed(self, stage: str, priority: str, age_seconds: float) -> None:
        if self.enabled:
            self.claims_total.labels(stage, priority).inc()
            self.task_age_seconds.labels(stage).observe(max(0.0, age_seconds))

    def retried(self, stage: str, reason: str) -> None:
        if self.enabled:
            self.task_retries_total.labels(stage, reason).inc()

    def failed(self, stage: str) -> None:
        if self.enabled:
            self.tasks_failed_total.labels(stage).inc()

    def fence_rejected(self, stage: str) -> None:
        if self.enabled:
            self.fence_rejections_total.labels(stage).inc()

    def lease_lost(self, stage: str) -> None:
        if self.enabled:
            self.lease_lost_total.labels(stage).inc()

    def outbox_publish_failed(self) -> None:
        if self.enabled:
            self.outbox_publish_failures_total.inc()

    def outbox_oldest_unsent(self, seconds: float) -> None:
        if self.enabled:
            self.outbox_oldest_unsent_seconds.set(max(0.0, seconds))

    def set_queue_depth(self, rows: Iterable[Tuple[str, str, int]]) -> None:
        """Set depth per (stage, priority); label sets that disappeared drop to 0."""
        if not self.enabled:
            return
        seen: Set[Tuple[str, str]] = set()
        for stage, priority, n in rows:
            self.queue_depth.labels(stage, priority).set(n)
            seen.add((stage, priority))
        for stale in self._depth_labels - seen:
            self.queue_depth.labels(*stale).set(0)
        self._depth_labels = seen | self._depth_labels


_default: Optional[IngestMetrics] = None
_default_lock = threading.Lock()


def default_metrics() -> IngestMetrics:
    """The process-wide metrics on the global registry (what /metrics serves)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = IngestMetrics()
        return _default


__all__ = ["IngestMetrics", "default_metrics"]
