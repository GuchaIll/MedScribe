"""
Error types for the ingest queue runtime.

Every error names the field or task it is about. None of them carry payload
or document text.
"""

from __future__ import annotations

from typing import Any, Optional


class IngestError(Exception):
    """Base class for ingest queue errors."""


class IngestConfigError(IngestError):
    """A queue config value is missing, the wrong type, or out of range."""

    def __init__(self, field: str, value: Any, expected: str) -> None:
        super().__init__(f"invalid ingest config {field}={value!r}: expected {expected}")
        self.field = field
        self.value = value
        self.expected = expected


class IngestInputError(IngestError):
    """An argument to a queue function (enqueue, outbox write, ...) is invalid."""

    def __init__(self, field: str, value: Any, expected: str) -> None:
        super().__init__(f"invalid {field}={value!r}: expected {expected}")
        self.field = field
        self.value = value
        self.expected = expected


class LeaseLostError(IngestError):
    """Renewal returned zero rows: the lease is gone and the work must be abandoned."""

    def __init__(self, task_id: int, stage: str) -> None:
        super().__init__(f"lease lost for task_id={task_id} stage={stage}")
        self.task_id = task_id
        self.stage = stage


class FenceRejectedError(IngestError):
    """The fence returned zero rows: the output transaction was rolled back."""

    def __init__(self, task_id: int, stage: str) -> None:
        super().__init__(f"fence rejected for task_id={task_id} stage={stage}")
        self.task_id = task_id
        self.stage = stage


class UnknownStageError(IngestError):
    """No stage is registered under this name."""

    def __init__(self, stage: str, registered: Optional[list] = None) -> None:
        known = ", ".join(sorted(registered or [])) or "none"
        super().__init__(f"unknown stage {stage!r}; registered: {known}")
        self.stage = stage


class StageContractError(IngestError):
    """A stage object does not satisfy the Stage interface."""

    def __init__(self, stage: str, problem: str) -> None:
        super().__init__(f"stage {stage!r} violates the Stage contract: {problem}")
        self.stage = stage
        self.problem = problem


__all__ = [
    "IngestError",
    "IngestConfigError",
    "IngestInputError",
    "LeaseLostError",
    "FenceRejectedError",
    "UnknownStageError",
    "StageContractError",
]
