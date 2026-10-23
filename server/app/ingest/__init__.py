"""
Ingest queue runtime (SDD §5.2.3.3, T2 / #92).

Lifecycle before payload: claim, lease, fence, retry, and the reconciler,
proven against a no-op stage. Nothing here knows what a document, page,
chunk, or OCR result is. Real stages (#93, #59, #54) implement `Stage`.
"""

from .claim import ClaimedTask
from .config import IngestQueueConfig
from .errors import (
    FenceRejectedError,
    IngestConfigError,
    IngestError,
    IngestInputError,
    LeaseLostError,
    StageContractError,
    UnknownStageError,
)
from .stage import Stage, StageRegistry

__all__ = [
    "ClaimedTask",
    "IngestQueueConfig",
    "IngestError",
    "IngestConfigError",
    "IngestInputError",
    "LeaseLostError",
    "FenceRejectedError",
    "UnknownStageError",
    "StageContractError",
    "Stage",
    "StageRegistry",
]
