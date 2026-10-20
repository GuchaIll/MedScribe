"""
get_patient_profile — real tool over the session snapshot (Phase 1A, #51).

Plan §18.2: this tool's backend is the session snapshot (§6.1), and the
snapshot is real in Phase 1A even while retrieval backends are stubbed. It
replaces ``load_patient_context_node``'s direct DB reads and
``PatientLookupTool``.

Citation: record id plus snapshot version, as §18.2 requires. The citation's
``evidence_state`` is ``authorized`` because a snapshot is built from finalized
records only; ``received_at`` is when the snapshot was loaded.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..session.snapshot import (
    SECTION_FACT_TYPES,
    PatientContextSnapshot,
    load_snapshot,
    snapshot_sections,
)
from ..tool_contracts import NO_SOURCE_ERROR
from .registry import ToolCall, ToolOutcome, ToolRegistry

logger = logging.getLogger(__name__)

TOOL_VERSION = "snapshot-1.2.0"

# Sections a caller may request; "all" (the default) returns every one. The
# clinical sections come from the snapshot's section views, so this list and
# the snapshot cannot drift apart.
PROFILE_SECTIONS = ("demographics", *SECTION_FACT_TYPES, "recent_visits_index")


def make_handler(ctx: Optional[Any] = None, *, store: Optional[Any] = None):
    """Build the ``get_patient_profile`` handler bound to an AgentContext."""

    def handler(call: ToolCall) -> ToolOutcome:
        patient_id = call.scope.patient_id
        if not patient_id:
            logger.warning(
                "get_patient_profile called without a patient in scope: session_id=%s",
                call.scope.session_id,
            )
            return ToolOutcome(
                ok=False,
                data={"reason": "no patient in session scope"},
                error=NO_SOURCE_ERROR,
            )

        sections = _requested_sections(call.args.get("sections"))
        snapshot = load_snapshot(
            call.scope.session_id,
            patient_id,
            ctx,
            tenant_id=call.scope.tenant_id,
            store=store,
        )
        cache_hit = snapshot["source"] == "cache"

        if not snapshot["loaded_from_db"]:
            logger.info(
                "get_patient_profile: empty snapshot for patient_id=%s (no finalized record)",
                patient_id,
            )
            return ToolOutcome(
                ok=False,
                data={"reason": "no materialized prior state for this patient",
                      "snapshot_version": snapshot["version"]},
                error=NO_SOURCE_ERROR,
                cache_hit=cache_hit,
            )

        payload = snapshot_sections(snapshot, sections)
        record_id = snapshot["retrieval_keys"].get("latest_record_id")
        return ToolOutcome(
            ok=True,
            data={
                "sections": payload,
                "snapshot_version": snapshot["version"],
                "loaded_at": snapshot["loaded_at"],
                "cache_hit": cache_hit,
            },
            citations=[_snapshot_citation(snapshot, record_id)],
            cache_hit=cache_hit,
            source_refs=[_source_id(snapshot, record_id)],
        )

    return handler


def register_profile_tool(
    registry: ToolRegistry,
    ctx: Optional[Any] = None,
    *,
    store: Optional[Any] = None,
    replace: bool = True,
) -> None:
    """Register the real ``get_patient_profile``, replacing any stub."""
    registry.register(
        "get_patient_profile",
        make_handler(ctx, store=store),
        version=TOOL_VERSION,
        stub=False,
        requires_scope=["patient_id"],
        replace=replace,
    )


def _requested_sections(requested: Any) -> List[str]:
    """Validate the model-visible ``sections[]`` argument."""
    if requested in (None, "all", []):
        return list(PROFILE_SECTIONS)
    if isinstance(requested, str):
        requested = [requested]
    if not isinstance(requested, list) or not all(isinstance(name, str) for name in requested):
        raise ValueError(
            f"sections must be a list of strings from {list(PROFILE_SECTIONS)}, got {requested!r}"
        )
    unknown = [name for name in requested if name not in PROFILE_SECTIONS]
    if unknown:
        raise ValueError(
            f"unknown profile sections {unknown}; expected any of {list(PROFILE_SECTIONS)}"
        )
    return requested


def _source_id(snapshot: PatientContextSnapshot, record_id: Optional[str]) -> str:
    base = record_id or f"patient:{snapshot['patient_id']}"
    return f"{base}#v{snapshot['version']}"


def _snapshot_citation(
    snapshot: PatientContextSnapshot,
    record_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "source_kind": "patient_snapshot",
        "source_id": _source_id(snapshot, record_id),
        "snippet": None,
        "observed_at": None,
        "received_at": snapshot["loaded_at"],
        "evidence_state": "authorized",
        "locator": None,
        "score": None,
    }


__all__ = ["PROFILE_SECTIONS", "TOOL_VERSION", "make_handler", "register_profile_tool"]
