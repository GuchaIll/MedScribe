"""
Parallel tool group runner (agent refactor Phase 1A, #51).

Plan §18.5: a workflow, cascade level, or plan step may run independent tools
in parallel. Parallelism is in-node on a thread pool, and each call opens its
own SQLAlchemy session because sessions are not thread-safe.

One failing call never sinks the group: it comes back as its own failed
ToolResult, in request order, beside the calls that succeeded.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..tool_contracts import RUNTIME_CONTRACT_VERSION, ToolResult
from ..tracing import utcnow_iso
from .errors import ToolRuntimeError
from .registry import ToolRegistry, hash_args

logger = logging.getLogger(__name__)

# Upper bound on threads per group. Plan §18.5 caps a workflow at 6 tools, so
# a group never needs more than that many workers.
MAX_GROUP_WORKERS = 6

# ToolResult.error when the registry refused the call outright (permission,
# unknown tool, bad args). The group still returns; the caller sees the reason.
REFUSED_ERROR = "refused"


@dataclass
class ToolRequest:
    """One member of a parallel group."""

    tool_id: str
    args: Dict[str, Any] = field(default_factory=dict)
    caller: str = "fixed_executor"
    caller_ref: str = ""
    model_supplied: bool = False
    evidence_class: Optional[str] = None
    gate_required: bool = False
    parent_span_id: Optional[str] = None


def run_parallel_group(
    registry: ToolRegistry,
    requests: List[ToolRequest],
    *,
    trace_log: Optional[List[Dict[str, Any]]] = None,
    db_session_factory: Optional[Callable[[], Any]] = None,
    max_workers: int = MAX_GROUP_WORKERS,
) -> List[ToolResult]:
    """Run independent tool calls concurrently; return results in request order.

    Each call gets its own DB session from ``db_session_factory`` (falling back
    to the registry's), used only by that call and closed when it returns.
    Receipts are collected per call and merged into ``trace_log`` in request
    order once the group finishes, so the log reads the same on every run.
    """
    if not requests:
        return []
    for request in requests:
        if not isinstance(request, ToolRequest):
            raise TypeError(
                f"parallel group members must be ToolRequest, got {type(request).__name__}"
            )
    if max_workers < 1:
        raise ValueError(f"max_workers must be >= 1, got {max_workers}")

    factory = db_session_factory or registry.db_session_factory
    # Receipts land in a per-call list, then merge in request order below, so
    # the trace log reads deterministically no matter how threads interleave.
    per_call_logs: List[List[Dict[str, Any]]] = [[] for _ in requests]

    if len(requests) == 1:
        results = [_run_one(registry, requests[0], per_call_logs[0], factory)]
    else:
        workers = min(max_workers, len(requests))
        logger.debug(
            "parallel tool group: size=%d workers=%d tools=%s",
            len(requests), workers, [r.tool_id for r in requests],
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tool-group") as pool:
            futures = [
                pool.submit(_run_one, registry, request, per_call_logs[index], factory)
                for index, request in enumerate(requests)
            ]
            results = [future.result() for future in futures]

    if trace_log is not None:
        for entries in per_call_logs:
            trace_log.extend(entries)

    failed = sum(1 for result in results if not result["ok"])
    if failed:
        logger.warning(
            "parallel tool group finished with failures: size=%d failed=%d",
            len(results), failed,
        )
    return results


def _run_one(
    registry: ToolRegistry,
    request: ToolRequest,
    call_log: List[Dict[str, Any]],
    db_session_factory: Optional[Callable[[], Any]],
) -> ToolResult:
    """Run one member of the group with its own DB session."""
    session = None
    if db_session_factory is not None:
        try:
            session = db_session_factory()
        except Exception:
            logger.exception(
                "could not open a DB session for tool_id=%s; running without one",
                request.tool_id,
            )
    try:
        return registry.call(
            request.tool_id,
            request.args,
            caller=request.caller,
            caller_ref=request.caller_ref,
            trace_log=call_log,
            model_supplied=request.model_supplied,
            evidence_class=request.evidence_class,
            gate_required=request.gate_required,
            parent_span_id=request.parent_span_id,
            db=session,
        )
    except ToolRuntimeError as exc:
        # A refusal is data for the caller, not an exception that kills siblings.
        logger.warning(
            "tool call refused inside parallel group: tool_id=%s reason=%s",
            request.tool_id, exc,
        )
        return _refusal_result(registry, request, str(exc))
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # pragma: no cover - close failures are not actionable
                logger.warning("failed to close DB session for tool_id=%s", request.tool_id)


def _refusal_result(registry: ToolRegistry, request: ToolRequest, reason: str) -> ToolResult:
    """A contract-valid failed result for a call the registry refused."""
    return {
        "tool_id": request.tool_id,  # type: ignore[typeddict-item]
        "ok": False,
        "data": {"refusal_reason": reason},
        "citations": [],
        "error": REFUSED_ERROR,
        "receipt": {
            "contract_version": RUNTIME_CONTRACT_VERSION,
            "invocation_id": str(uuid.uuid4()),
            "session_id": registry.scope.session_id,
            "tool_id": request.tool_id,  # type: ignore[typeddict-item]
            "tool_version": "unregistered",
            "caller": request.caller,  # type: ignore[typeddict-item]
            "caller_ref": request.caller_ref,
            "args_hash": hash_args(request.args),
            "ok": False,
            "error": REFUSED_ERROR,
            "cache_hit": False,
            "latency_ms": 0.0,
            "source_refs": [],
            "created_at": utcnow_iso(),
        },
    }


__all__ = ["MAX_GROUP_WORKERS", "REFUSED_ERROR", "ToolRequest", "run_parallel_group"]
