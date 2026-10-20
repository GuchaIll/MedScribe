"""
Patient information state for one session (agent refactor Phase 1A onward).

- ``snapshot`` — PatientContextSnapshot: materialized prior state, loaded once
  per session and invalidated on the §6.2 triggers (#51)
- ``artifact_index`` — per-document ingest state (#59)
- ``receipt_ledger`` — what was received by the query cutoff (#84)
"""

from .snapshot import (
    PatientContextSnapshot,
    SnapshotStore,
    empty_snapshot,
    get_snapshot_store,
    invalidate_snapshot,
    load_snapshot,
)

__all__ = [
    "PatientContextSnapshot",
    "SnapshotStore",
    "empty_snapshot",
    "get_snapshot_store",
    "invalidate_snapshot",
    "load_snapshot",
]
