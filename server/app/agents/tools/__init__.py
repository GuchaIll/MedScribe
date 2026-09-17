"""
Agent tools — one registry, three callers (agent refactor Phase 1A, #51).

Lane B stages, fixed assist workflows, and the planning agent all reach tools
through ``ToolRegistry``. ``build_registry`` wires the registry a call site
needs: real tools where they exist (session snapshot, safety engines) and
fixture-backed stubs everywhere else until Phase 1B lands the real backends.

Retired in #51: ``PatientLookupTool`` (replaced by the session snapshot) and
``ToolUniverseService`` (replaced by the three safety tools).
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from .drug_checker import DrugCheckerTool
from .errors import (
    ToolArgumentError,
    ToolPermissionError,
    ToolResultContractError,
    ToolRuntimeError,
    ToolScopeError,
    UnknownToolError,
)
from .llm import LLMTool
from .ocr_reader import OCRReaderTool
from .profile import register_profile_tool
from .registry import (
    RegisteredTool,
    ToolCall,
    ToolOutcome,
    ToolRegistry,
    ToolScope,
)
from .runner import ToolRequest, run_parallel_group
from .safety import register_safety_tools
from .stubs import StubToolSet, register_stub_tools

logger = logging.getLogger(__name__)

# Tools with a real backend in Phase 1A. Everything else is still a stub.
REAL_TOOL_IDS = (
    "get_patient_profile",
    "check_med_conflicts",
    "check_dosage",
    "check_metric_alerts",
)


def build_registry(
    scope: ToolScope,
    ctx: Optional[Any] = None,
    *,
    with_stubs: bool = True,
    stub_case: str = "ok",
    trace_sink: Optional[Any] = None,
    metrics: Optional[Any] = None,
    snapshot_store: Optional[Any] = None,
    trace_id: Optional[str] = None,
) -> ToolRegistry:
    """Build a registry for one session scope.

    Real tools are registered first; stubs fill the remaining contract ids only
    when ``with_stubs`` is set, so a production call site can choose to fail
    loudly on an unimplemented tool instead of answering from fixtures.
    """
    registry = ToolRegistry(
        scope,
        trace_sink=trace_sink,
        metrics=metrics,
        db_session_factory=getattr(ctx, "db_session_factory", None),
        trace_id=trace_id,
    )
    register_profile_tool(registry, ctx, store=snapshot_store, replace=False)
    register_safety_tools(registry, ctx, replace=False)
    if with_stubs:
        register_stub_tools(registry, case=stub_case, skip=list(REAL_TOOL_IDS))
    logger.debug(
        "registry built: session_id=%s tools=%d stubs=%s",
        scope.session_id, len(registry.registered()), with_stubs,
    )
    return registry


def stubbed_tool_ids(registry: ToolRegistry) -> List[str]:
    """Tool ids currently served by a stub — useful in evals and tests."""
    return sorted(tool_id for tool_id, tool in registry.registered().items() if tool.stub)


__all__ = [
    "REAL_TOOL_IDS",
    "DrugCheckerTool",
    "LLMTool",
    "OCRReaderTool",
    "RegisteredTool",
    "StubToolSet",
    "ToolArgumentError",
    "ToolCall",
    "ToolOutcome",
    "ToolPermissionError",
    "ToolRegistry",
    "ToolRequest",
    "ToolResultContractError",
    "ToolRuntimeError",
    "ToolScope",
    "ToolScopeError",
    "UnknownToolError",
    "build_registry",
    "register_profile_tool",
    "register_safety_tools",
    "register_stub_tools",
    "run_parallel_group",
    "stubbed_tool_ids",
]
