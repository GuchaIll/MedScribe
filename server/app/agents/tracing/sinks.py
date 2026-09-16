"""
Trace sinks for the agent runtime.

TraceSink    — protocol every sink implements
JsonlTraceSink   — dev/eval: one JSON line per span, one file per run
PostgresTraceSink — production: interface only; full impl lands with migration
PrometheusMetrics — derived counters/histograms; registration only here
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..trace_contracts import TraceSpan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TraceSink(Protocol):
    def emit(self, span: "TraceSpan") -> None:
        ...

    def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# JSONL sink — dev and eval runs; one file per run; replayable
# ---------------------------------------------------------------------------


class JsonlTraceSink:
    """
    Appends one JSON line per span to a file.
    Thread-safe via the GIL for CPython; not process-safe across workers.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    def emit(self, span: "TraceSpan") -> None:
        try:
            self._fh.write(json.dumps(dict(span)) + "\n")
            self._fh.flush()
        except Exception:
            logger.exception("JsonlTraceSink.emit failed")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Postgres sink — interface only; full impl coordinated with #48 migration
# ---------------------------------------------------------------------------


class PostgresTraceSink:
    """
    Writes spans to the agent_trace_spans table.

    Full implementation lands with the Alembic migration (this issue).
    Instantiating this class before the table exists will raise on first emit.
    """

    def emit(self, span: "TraceSpan") -> None:
        raise NotImplementedError(
            "PostgresTraceSink is not yet implemented. "
            "Run the agent_trace_spans migration and implement the insert."
        )

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Prometheus metrics — registration only; increments land per-node in Phase 1A
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Histogram  # type: ignore[import-untyped]

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


class PrometheusMetrics:
    """
    Registers all agent-runtime Prometheus metrics.

    Metrics are defined here so every phase imports from one place.
    If prometheus_client is not installed the attributes are None and
    callers should guard with `if metrics.dispatch_total:`.
    """

    dispatch_total: Optional[Any]
    dispatch_latency_ms: Optional[Any]
    tool_call_total: Optional[Any]
    tool_error_total: Optional[Any]
    tool_latency_ms: Optional[Any]
    llm_input_tokens_total: Optional[Any]
    llm_output_tokens_total: Optional[Any]
    llm_cost_usd_total: Optional[Any]
    refusal_total: Optional[Any]
    guardrail_violation_total: Optional[Any]
    materialization_wait_ms: Optional[Any]
    handoff_total: Optional[Any]

    def __init__(self, namespace: str = "medscribe_agent") -> None:
        if not _PROMETHEUS_AVAILABLE:
            logger.warning(
                "prometheus_client not installed; PrometheusMetrics will be no-ops. "
                "Add prometheus_client to requirements.txt."
            )
            for attr in self.__class__.__annotations__:
                setattr(self, attr, None)
            return

        self.dispatch_total = Counter(
            f"{namespace}_dispatch_total",
            "Assist requests dispatched, by dispatch value",
            ["dispatch", "dispatch_rule"],
        )
        self.dispatch_latency_ms = Histogram(
            f"{namespace}_dispatch_latency_ms",
            "Route + dispatch latency in ms",
            buckets=[5, 10, 25, 50, 100, 200, 500, 1000],
        )
        self.tool_call_total = Counter(
            f"{namespace}_tool_call_total",
            "Tool calls, by tool_id and stub flag",
            ["tool_id", "stub", "ok"],
        )
        self.tool_error_total = Counter(
            f"{namespace}_tool_error_total",
            "Tool call errors, by tool_id",
            ["tool_id"],
        )
        self.tool_latency_ms = Histogram(
            f"{namespace}_tool_latency_ms",
            "Tool call latency in ms, by tool_id",
            ["tool_id", "stub"],
            buckets=[5, 25, 100, 250, 500, 1000, 5000],
        )
        self.llm_input_tokens_total = Counter(
            f"{namespace}_llm_input_tokens_total",
            "LLM input tokens consumed, by model_role and model",
            ["model_role", "model"],
        )
        self.llm_output_tokens_total = Counter(
            f"{namespace}_llm_output_tokens_total",
            "LLM output tokens produced, by model_role and model",
            ["model_role", "model"],
        )
        self.llm_cost_usd_total = Counter(
            f"{namespace}_llm_cost_usd_total",
            "Estimated LLM cost in USD, by model_role",
            ["model_role"],
        )
        self.refusal_total = Counter(
            f"{namespace}_refusal_total",
            "Requests refused (scope, guardrail, cap), by reason",
            ["reason"],
        )
        self.guardrail_violation_total = Counter(
            f"{namespace}_guardrail_violation_total",
            "Guardrail violations detected, by rule",
            ["rule"],
        )
        self.materialization_wait_ms = Histogram(
            f"{namespace}_materialization_wait_ms",
            "Wait for in-flight document materialization in ms",
            buckets=[50, 100, 250, 500, 1000, 3000, 10000],
        )
        self.handoff_total = Counter(
            f"{namespace}_handoff_total",
            "Workflow handoffs to planner, by reason",
            ["reason"],
        )


# Module-level singleton; replaced in tests with a fresh instance.
_metrics: Optional[PrometheusMetrics] = None


def get_metrics() -> PrometheusMetrics:
    global _metrics
    if _metrics is None:
        _metrics = PrometheusMetrics(
            namespace=os.environ.get("PROMETHEUS_NAMESPACE", "medscribe_agent")
        )
    return _metrics
