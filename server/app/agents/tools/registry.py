"""
Shared tool registry runtime (agent refactor Phase 1A, #51).

One capability, three callers. Lane B compile stages, fixed assist workflows,
and the planning agent all reach tools through ``ToolRegistry.call()``, so
permissions, patient scope, citation rules, receipts, and spans cannot drift
between them.

Every call:
  1. resolves the tool and checks the caller may use it (tool_contracts.TOOL_SPECS)
  2. rejects model-supplied scope keys (validate_model_tool_args)
  3. injects the runtime scope the model may never supply
  4. runs the handler with its own DB session when the tool needs one
  5. validates the result against the contract (validate_tool_result)
  6. writes one receipt to controls.trace_log and emits one tool_call span

Sources: plan §11 Phase 1A item 2, §18.5; contract §6; design tree
agents/tools/registry.py.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..tool_contracts import (
    RUNTIME_CONTRACT_VERSION,
    SCOPE_ARG_KEYS,
    TOOL_SPECS,
    ToolInvocationReceipt,
    ToolResult,
    validate_model_tool_args,
    validate_tool_result,
)
from ..tracing import (
    build_tool_call_attrs,
    new_span_id,
    new_trace_id,
    utcnow_iso,
)
from ..tracing.spans import sha256_hex
from ..trace_contracts import make_span
from .errors import (
    ToolArgumentError,
    ToolPermissionError,
    ToolResultContractError,
    ToolScopeError,
    UnknownToolError,
)

logger = logging.getLogger(__name__)

# Receipts and trace_log entries are typed by this event name in §19.2.
TOOL_INVOCATION_EVENT = "tool.invocation"

# Returned as ToolResult.error when a handler raises. The exception never
# escapes into the graph; the failure is visible in the receipt and the span.
HANDLER_ERROR = "handler_error"


# ---------------------------------------------------------------------------
# Runtime scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolScope:
    """Identifiers the runtime injects. A model may never supply these.

    The field set is exactly ``SCOPE_ARG_KEYS`` from the contract, so the keys
    the registry rejects in model args and the keys it injects stay in step.
    """

    session_id: str
    patient_id: Optional[str] = None
    tenant_id: Optional[str] = None
    doctor_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.session_id or not isinstance(self.session_id, str):
            raise ValueError(
                f"ToolScope.session_id must be a non-empty string, got {self.session_id!r}"
            )

    def as_dict(self) -> Dict[str, str]:
        """Scope identifiers that are set, as a plain dict for handlers."""
        return {
            key: value
            for key, value in (
                ("session_id", self.session_id),
                ("patient_id", self.patient_id),
                ("tenant_id", self.tenant_id),
                ("doctor_id", self.doctor_id),
            )
            if value
        }

    def missing(self, required: List[str]) -> List[str]:
        """Return the required scope keys that are absent."""
        present = self.as_dict()
        return [key for key in required if not present.get(key)]


# Every scope field must be a contract scope key; a mismatch would let a model
# smuggle an identifier the registry does not strip.
assert set(ToolScope.__dataclass_fields__) == set(SCOPE_ARG_KEYS), (
    "ToolScope fields must match tool_contracts.SCOPE_ARG_KEYS"
)


# ---------------------------------------------------------------------------
# Handler interface
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """Everything a handler is given. Handlers read scope from here, not args."""

    tool_id: str
    args: Dict[str, Any]
    scope: ToolScope
    caller: str
    caller_ref: str
    invocation_id: str
    db: Optional[Any] = None            # SQLAlchemy Session, one per call
    evidence_class: Optional[str] = None


@dataclass
class ToolOutcome:
    """What a handler returns. The registry turns it into a ToolResult."""

    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    cache_hit: bool = False
    source_refs: List[str] = field(default_factory=list)


ToolHandler = Callable[[ToolCall], ToolOutcome]


@dataclass(frozen=True)
class RegisteredTool:
    tool_id: str
    handler: ToolHandler
    version: str
    stub: bool
    needs_db: bool
    requires_scope: tuple


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Executes contract 1.2 tools for one session scope."""

    def __init__(
        self,
        scope: ToolScope,
        *,
        trace_sink: Optional[Any] = None,
        metrics: Optional[Any] = None,
        db_session_factory: Optional[Callable[[], Any]] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        if not isinstance(scope, ToolScope):
            raise TypeError(f"scope must be a ToolScope, got {type(scope).__name__}")
        self.scope = scope
        self.trace_sink = trace_sink
        self.metrics = metrics
        self.db_session_factory = db_session_factory
        self.trace_id = trace_id or new_trace_id()
        self._tools: Dict[str, RegisteredTool] = {}

    # -- registration ------------------------------------------------------

    def register(
        self,
        tool_id: str,
        handler: ToolHandler,
        *,
        version: str = "1.0.0",
        stub: bool = False,
        needs_db: bool = False,
        requires_scope: Optional[List[str]] = None,
        replace: bool = False,
    ) -> None:
        """Register a handler for a contract tool id.

        ``replace=True`` is how a real backend takes over from a stub, one tool
        at a time, as Phase 1B lands.
        """
        if tool_id not in TOOL_SPECS:
            raise UnknownToolError(
                f"cannot register {tool_id!r}: not a contract {RUNTIME_CONTRACT_VERSION} tool id",
                tool_id=tool_id,
            )
        if not callable(handler):
            raise TypeError(f"handler for {tool_id!r} must be callable")
        if tool_id in self._tools and not replace:
            raise ValueError(
                f"{tool_id!r} is already registered; pass replace=True to override "
                f"(current version {self._tools[tool_id].version})"
            )
        for key in requires_scope or []:
            if key not in SCOPE_ARG_KEYS:
                raise ValueError(
                    f"requires_scope for {tool_id!r} contains {key!r}, "
                    f"which is not a scope key {sorted(SCOPE_ARG_KEYS)}"
                )
        self._tools[tool_id] = RegisteredTool(
            tool_id=tool_id,
            handler=handler,
            version=version,
            stub=stub,
            needs_db=needs_db,
            requires_scope=tuple(requires_scope or ()),
        )
        logger.debug(
            "tool registered: tool_id=%s version=%s stub=%s needs_db=%s",
            tool_id, version, stub, needs_db,
        )

    def registered(self) -> Dict[str, RegisteredTool]:
        return dict(self._tools)

    def is_stub(self, tool_id: str) -> bool:
        tool = self._tools.get(tool_id)
        return bool(tool and tool.stub)

    # -- permissions -------------------------------------------------------

    @staticmethod
    def permission_error(tool_id: str, caller: str, caller_ref: str) -> Optional[str]:
        """Return why this caller may not call this tool, or None if allowed."""
        spec = TOOL_SPECS.get(tool_id)
        if spec is None:
            return f"unknown tool {tool_id!r}"
        if caller == "planning_agent":
            if not spec["planner_allowlisted"]:
                return f"{tool_id} is not planner-allowlisted"
            return None
        if caller == "fixed_executor":
            if not spec["assist_callable"]:
                return f"{tool_id} is not callable from the assist path"
            return None
        if caller == "lane_b_stage":
            if not spec["lane_b_stages"]:
                return f"{tool_id} is not a compile step"
            if caller_ref not in spec["lane_b_stages"]:
                return (
                    f"{tool_id} is not callable from Lane B stage {caller_ref!r}; "
                    f"allowed stages: {list(spec['lane_b_stages'])}"
                )
            return None
        return f"unknown caller {caller!r}"

    # -- invocation --------------------------------------------------------

    def call(
        self,
        tool_id: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        caller: str,
        caller_ref: str,
        trace_log: Optional[List[Dict[str, Any]]] = None,
        model_supplied: bool = False,
        evidence_class: Optional[str] = None,
        gate_required: bool = False,
        parent_span_id: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> ToolResult:
        """Run one tool and return a contract-valid ToolResult.

        ``model_supplied=True`` marks args a model proposed: those go through
        ``validate_model_tool_args`` so a smuggled ``patient_id`` is refused.
        Runtime-built args are still checked for scope keys, because injecting
        them twice would let a stale id override the session scope.
        """
        args = {} if args is None else args
        if not isinstance(caller_ref, str) or not caller_ref:
            raise ValueError(f"caller_ref must be a non-empty string, got {caller_ref!r}")

        tool = self._tools.get(tool_id)
        if tool is None:
            known = tool_id in TOOL_SPECS
            raise UnknownToolError(
                f"{tool_id!r} is not registered"
                + ("" if known else f" and is not a contract {RUNTIME_CONTRACT_VERSION} tool id"),
                tool_id=tool_id,
            )

        denial = self.permission_error(tool_id, caller, caller_ref)
        if denial is not None:
            logger.warning(
                "tool call refused: tool_id=%s caller=%s caller_ref=%s reason=%s",
                tool_id, caller, caller_ref, denial,
            )
            raise ToolPermissionError(denial, tool_id=tool_id, caller=caller, caller_ref=caller_ref)

        violations = validate_model_tool_args(tool_id, args)
        if violations:
            logger.warning(
                "tool args rejected: tool_id=%s caller=%s model_supplied=%s violations=%d",
                tool_id, caller, model_supplied, len(violations),
            )
            raise ToolArgumentError(
                f"invalid args for {tool_id}: {'; '.join(violations)}",
                tool_id=tool_id,
                violations=violations,
            )

        missing_scope = self.scope.missing(list(tool.requires_scope))
        if missing_scope:
            raise ToolScopeError(
                f"{tool_id} needs scope keys {missing_scope} but the session scope has none",
                tool_id=tool_id,
                missing=missing_scope,
            )

        invocation_id = str(uuid.uuid4())
        started_at = utcnow_iso()
        started = time.perf_counter()
        owned_session = None
        outcome: ToolOutcome

        try:
            if db is None and tool.needs_db and self.db_session_factory is not None:
                owned_session = self.db_session_factory()
            call = ToolCall(
                tool_id=tool_id,
                args=args,
                scope=self.scope,
                caller=caller,
                caller_ref=caller_ref,
                invocation_id=invocation_id,
                db=db if db is not None else owned_session,
                evidence_class=evidence_class,
            )
            outcome = tool.handler(call)
            if not isinstance(outcome, ToolOutcome):
                raise ToolResultContractError(
                    f"handler for {tool_id} returned {type(outcome).__name__}, expected ToolOutcome",
                    tool_id=tool_id,
                    violations=["handler did not return a ToolOutcome"],
                )
        except ToolResultContractError:
            raise
        except Exception as exc:  # handler failure must not break the graph
            logger.exception(
                "tool handler failed: tool_id=%s invocation_id=%s caller=%s error_type=%s",
                tool_id, invocation_id, caller, type(exc).__name__,
            )
            outcome = ToolOutcome(ok=False, error=HANDLER_ERROR)
        finally:
            if owned_session is not None:
                try:
                    owned_session.close()
                except Exception:  # pragma: no cover - close failures are not actionable
                    logger.warning(
                        "failed to close DB session for tool_id=%s invocation_id=%s",
                        tool_id, invocation_id,
                    )

        latency_ms = (time.perf_counter() - started) * 1000.0
        receipt = self._build_receipt(
            tool=tool,
            invocation_id=invocation_id,
            caller=caller,
            caller_ref=caller_ref,
            args=args,
            outcome=outcome,
            latency_ms=latency_ms,
        )
        result: ToolResult = {
            "tool_id": tool_id,
            "ok": outcome.ok,
            "data": outcome.data,
            "citations": outcome.citations,
            "error": outcome.error,
            "receipt": receipt,
        }

        result_violations = validate_tool_result(dict(result))
        if result_violations:
            logger.error(
                "tool result violates contract: tool_id=%s invocation_id=%s violations=%s",
                tool_id, invocation_id, result_violations,
            )
            self._emit_span(
                tool=tool, receipt=receipt, evidence_class=evidence_class,
                gate_required=gate_required, started_at=started_at,
                latency_ms=latency_ms, parent_span_id=parent_span_id, status="error",
            )
            raise ToolResultContractError(
                f"{tool_id} returned an invalid ToolResult: {'; '.join(result_violations)}",
                tool_id=tool_id,
                violations=result_violations,
            )

        self._record(
            tool=tool,
            receipt=receipt,
            trace_log=trace_log,
            evidence_class=evidence_class,
            gate_required=gate_required,
            started_at=started_at,
            latency_ms=latency_ms,
            parent_span_id=parent_span_id,
        )
        logger.info(
            "tool call: tool_id=%s caller=%s caller_ref=%s ok=%s stub=%s "
            "cache_hit=%s citations=%d latency_ms=%.1f invocation_id=%s",
            tool_id, caller, caller_ref, outcome.ok, tool.stub, outcome.cache_hit,
            len(outcome.citations), latency_ms, invocation_id,
        )
        return result

    # -- receipts, trace log, spans, metrics --------------------------------

    def _build_receipt(
        self,
        *,
        tool: RegisteredTool,
        invocation_id: str,
        caller: str,
        caller_ref: str,
        args: Dict[str, Any],
        outcome: ToolOutcome,
        latency_ms: float,
    ) -> ToolInvocationReceipt:
        source_refs = outcome.source_refs or [
            str(citation.get("source_id"))
            for citation in outcome.citations
            if isinstance(citation, dict) and citation.get("source_id")
        ]
        return ToolInvocationReceipt(
            contract_version=RUNTIME_CONTRACT_VERSION,
            invocation_id=invocation_id,
            session_id=self.scope.session_id,
            tool_id=tool.tool_id,  # type: ignore[typeddict-item]
            tool_version=tool.version,
            caller=caller,  # type: ignore[typeddict-item]
            caller_ref=caller_ref,
            args_hash=hash_args(args),
            ok=outcome.ok,
            error=outcome.error,
            cache_hit=outcome.cache_hit,
            latency_ms=latency_ms,
            source_refs=source_refs,
            created_at=utcnow_iso(),
        )

    def _record(
        self,
        *,
        tool: RegisteredTool,
        receipt: ToolInvocationReceipt,
        trace_log: Optional[List[Dict[str, Any]]],
        evidence_class: Optional[str],
        gate_required: bool,
        started_at: str,
        latency_ms: float,
        parent_span_id: Optional[str],
    ) -> None:
        if trace_log is not None:
            # stub lives beside the receipt, not inside it: contract 1.2 has no
            # stub field and stays frozen (plan doc, decision 1).
            trace_log.append({
                "event": TOOL_INVOCATION_EVENT,
                "stub": tool.stub,
                "evidence_class": evidence_class,
                **dict(receipt),
            })
        self._emit_span(
            tool=tool,
            receipt=receipt,
            evidence_class=evidence_class,
            gate_required=gate_required,
            started_at=started_at,
            latency_ms=latency_ms,
            parent_span_id=parent_span_id,
            status="ok" if receipt["ok"] else "error",
        )
        self._emit_metrics(tool=tool, receipt=receipt, latency_ms=latency_ms)

    def _emit_span(
        self,
        *,
        tool: RegisteredTool,
        receipt: ToolInvocationReceipt,
        evidence_class: Optional[str],
        gate_required: bool,
        started_at: str,
        latency_ms: float,
        parent_span_id: Optional[str],
        status: str,
    ) -> None:
        if self.trace_sink is None:
            return
        span = make_span(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            kind="tool_call",
            name=f"tool.{tool.tool_id}",
            session_id=self.scope.session_id,
            started_at=started_at,
            duration_ms=latency_ms,
            status=status,  # type: ignore[arg-type]
            parent_span_id=parent_span_id,
            attributes=build_tool_call_attrs(
                invocation_id=receipt["invocation_id"],
                tool_id=tool.tool_id,
                tool_version=tool.version,
                caller=receipt["caller"],
                args_hash=receipt["args_hash"],
                ok=receipt["ok"],
                error=receipt["error"],
                cache_hit=receipt["cache_hit"],
                latency_ms=latency_ms,
                source_refs=receipt["source_refs"],
                stub=tool.stub,
                gate_required=gate_required,
                evidence_class=evidence_class,
            ),
        )
        try:
            self.trace_sink.emit(span)
        except Exception:
            logger.warning(
                "trace sink rejected a tool_call span: tool_id=%s invocation_id=%s",
                tool.tool_id, receipt["invocation_id"],
            )

    def _emit_metrics(
        self,
        *,
        tool: RegisteredTool,
        receipt: ToolInvocationReceipt,
        latency_ms: float,
    ) -> None:
        if self.metrics is None:
            return
        stub_label = "true" if tool.stub else "false"
        try:
            if getattr(self.metrics, "tool_call_total", None):
                self.metrics.tool_call_total.labels(
                    tool_id=tool.tool_id, stub=stub_label, ok=str(receipt["ok"]).lower()
                ).inc()
            if getattr(self.metrics, "tool_latency_ms", None):
                self.metrics.tool_latency_ms.labels(
                    tool_id=tool.tool_id, stub=stub_label
                ).observe(latency_ms)
            if not receipt["ok"] and getattr(self.metrics, "tool_error_total", None):
                self.metrics.tool_error_total.labels(tool_id=tool.tool_id).inc()
        except Exception:
            logger.warning("metrics emit failed for tool_id=%s", tool.tool_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_args(args: Dict[str, Any]) -> str:
    """Stable hash of tool args. Receipts carry the hash, never the values."""
    try:
        payload = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = repr(sorted(args.items()))
    return sha256_hex(payload)


__all__ = [
    "HANDLER_ERROR",
    "TOOL_INVOCATION_EVENT",
    "RegisteredTool",
    "ToolCall",
    "ToolHandler",
    "ToolOutcome",
    "ToolRegistry",
    "ToolScope",
    "hash_args",
]
