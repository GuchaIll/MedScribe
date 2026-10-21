"""
The no-op stage: exercises the queue lifecycle with no payload.

compute() optionally sleeps and optionally raises; commit() writes nothing
unless a hook is given (the conformance suite records commits through one);
on_exhausted() writes one outbox row so exhaustion is observable.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from sqlalchemy.engine import Connection

from .claim import ClaimedTask
from .errors import StageContractError
from .outbox import write_outbox
from .stage import Stage

EXHAUSTED_TOPIC = "ingest.task.exhausted"


class InjectedFailure(RuntimeError):
    """Raised by the no-op stage when a test asks it to fail."""


class NoopStage(Stage):
    def __init__(
        self,
        name: str = "noop",
        *,
        sleep_seconds: float = 0.0,
        sleep_for: Optional[Callable[[ClaimedTask], float]] = None,
        fail_compute: Optional[Callable[[ClaimedTask], bool]] = None,
        commit_hook: Optional[Callable[[Connection, ClaimedTask], None]] = None,
        lease_seconds: Optional[int] = None,
    ) -> None:
        if sleep_seconds < 0:
            raise StageContractError(name, f"sleep_seconds must be >= 0, got {sleep_seconds}")
        self.name = name
        self.lease_seconds = lease_seconds
        self._sleep_seconds = sleep_seconds
        self._sleep_for = sleep_for
        self._fail_compute = fail_compute
        self._commit_hook = commit_hook

    def compute(self, task: ClaimedTask) -> Any:
        delay = self._sleep_for(task) if self._sleep_for is not None else self._sleep_seconds
        if delay > 0:
            time.sleep(delay)
        if self._fail_compute is not None and self._fail_compute(task):
            raise InjectedFailure(f"injected compute failure task_id={task.task_id} attempt={task.attempts}")
        return None

    def commit(self, conn: Connection, task: ClaimedTask, output: Any) -> None:
        if self._commit_hook is not None:
            self._commit_hook(conn, task)

    def on_exhausted(self, conn: Connection, task: ClaimedTask, last_error: str) -> None:
        write_outbox(
            conn,
            topic=EXHAUSTED_TOPIC,
            key=str(task.doc_id),
            payload={"task_id": task.task_id, "stage": task.stage, "attempts": task.attempts},
        )


__all__ = ["NoopStage", "InjectedFailure", "EXHAUSTED_TOPIC"]
