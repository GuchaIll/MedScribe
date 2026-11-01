"""Ephemeral forward-progress reporting for supervised ingest work."""

from __future__ import annotations

import threading
import time

from .claim import ClaimedTask
from .errors import IngestInputError


class TaskProgress:
    """Thread-safe monotonic progress clock owned by one claimed task.

    Reports intentionally carry no payload or clinical text.  A stage calls
    ``report`` only after a safe unit of forward work; the worker watchdog uses
    the monotonic timestamp to decide whether the process has become stale.
    """

    def __init__(self, task: ClaimedTask) -> None:
        if not isinstance(task, ClaimedTask):
            raise IngestInputError("task", type(task).__name__, "a ClaimedTask")
        self.task_id = task.task_id
        self._lock = threading.Lock()
        self._last_reported_monotonic = time.monotonic()

    def report(self) -> None:
        """Record a completed safe work unit for the watchdog."""
        with self._lock:
            self._last_reported_monotonic = time.monotonic()

    def seconds_since_report(self) -> float:
        """Return non-negative monotonic seconds since the latest report."""
        with self._lock:
            return max(0.0, time.monotonic() - self._last_reported_monotonic)


__all__ = ["TaskProgress"]
