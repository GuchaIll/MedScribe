"""
The Stage interface that T5 (page, #59) and T6 (finalize, #54) implement,
and the registry the worker and reconciler look stages up in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.engine import Connection

from app.logging import get_logger

from .claim import ClaimedTask
from .errors import StageContractError, UnknownStageError

logger = get_logger(__name__)

MIN_STAGE_LEASE_SECONDS = 5
MAX_STAGE_LEASE_SECONDS = 600


class Stage(ABC):
    """
    One kind of queue work. The engine owns claim, lease, fence, retry and
    exhaustion; a stage only computes and writes its outputs.

    `name` matches ingest_tasks.stage. `lease_seconds` overrides the config
    default for this stage (None = default); set it from measured task time.

    The output a stage returns from compute() is opaque to the engine and is
    handed back unchanged to commit().
    """

    name: str = ""
    lease_seconds: Optional[int] = None

    @abstractmethod
    def compute(self, task: ClaimedTask) -> Any:
        """
        Pure work. No DB transaction is open and the engine renews the lease
        while this runs. Raising schedules a retry (or exhaustion). The engine
        cannot interrupt compute on lease loss; it discards the output.
        """

    def before_commit(self, conn: Connection, task: ClaimedTask) -> None:
        """
        Runs in the output transaction right after the fence succeeded, before
        commit(). Use it only for `set local` (e.g. `app.patient_id` for RLS
        tables, C.4). Default: nothing.
        """

    @abstractmethod
    def commit(self, conn: Connection, task: ClaimedTask, output: Any) -> None:
        """
        Runs inside the output transaction after the fence returned a row. The
        fence already set the task `done`; raising rolls everything back and
        schedules a retry. Every effect must be a Postgres row (outputs,
        follow-on tasks via enqueue(), outbox rows via write_outbox(),
        pg_notify). Never call Redis, Kafka, HTTP, or the object store here.
        """

    @abstractmethod
    def on_exhausted(self, conn: Connection, task: ClaimedTask, last_error: str) -> None:
        """
        Runs in the transaction that marks the task `failed` at max attempts,
        from the worker or the reconciler. This is where a stage makes the
        document's terminal transition (#93 / #59). Same rules as commit().
        """


def validate_stage(stage: Any) -> Stage:
    """Check the parts of the contract that can be checked without running it."""
    label = getattr(stage, "name", repr(stage))
    if not isinstance(stage, Stage):
        raise StageContractError(str(label), f"must subclass Stage, got {type(stage).__name__}")
    if not isinstance(stage.name, str) or not stage.name.strip():
        raise StageContractError(str(label), f"name must be a non-empty string, got {stage.name!r}")
    lease = stage.lease_seconds
    if lease is not None and (
        isinstance(lease, bool)
        or not isinstance(lease, int)
        or not (MIN_STAGE_LEASE_SECONDS <= lease <= MAX_STAGE_LEASE_SECONDS)
    ):
        raise StageContractError(
            stage.name,
            f"lease_seconds must be None or an int in "
            f"[{MIN_STAGE_LEASE_SECONDS}, {MAX_STAGE_LEASE_SECONDS}], got {lease!r}",
        )
    return stage


class StageRegistry:
    """Name -> Stage. A process registers the stages it runs or reconciles."""

    def __init__(self, stages: Iterable[Stage] = ()) -> None:
        self._stages: Dict[str, Stage] = {}
        for s in stages:
            self.register(s)

    def register(self, stage: Stage) -> None:
        validate_stage(stage)
        if stage.name in self._stages:
            raise StageContractError(stage.name, "a stage with this name is already registered")
        self._stages[stage.name] = stage
        logger.info("ingest stage registered stage=%s lease_seconds=%s", stage.name, stage.lease_seconds)

    def get(self, name: str) -> Stage:
        try:
            return self._stages[name]
        except KeyError:
            raise UnknownStageError(name, list(self._stages)) from None

    def __contains__(self, name: object) -> bool:
        return name in self._stages

    def names(self) -> List[str]:
        return sorted(self._stages)


__all__ = ["Stage", "StageRegistry", "validate_stage"]
