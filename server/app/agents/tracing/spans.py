"""
PHI-free span attribute builders.

Each function returns a dict that becomes the `attributes` field of a TraceSpan.
No function accepts raw utterance text, prompt text, or tool payloads in
production mode.  Callers must hash / count / code any sensitive values before
passing them in.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# LLM span attributes (addressee, slot_extract, plan, render, synthesis, judge)
# ---------------------------------------------------------------------------


def build_llm_attrs(
    *,
    prompt_id: str,
    prompt_version: str,
    prompt_template_sha: str,
    model_role: str,
    provider: str,
    model: str,
    temperature: float,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    cost_usd: float,
    context_tokens_by_segment: Dict[str, int],
    schema_valid: bool,
    repair_retry: int,
    finish_reason: str,
) -> Dict[str, Any]:
    return {
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "prompt_sha": prompt_template_sha,
        "model_role": model_role,
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost_usd,
        "context_tokens_by_segment": context_tokens_by_segment,
        "schema_valid": schema_valid,
        "repair_retry": repair_retry,
        "finish_reason": finish_reason,
    }


# ---------------------------------------------------------------------------
# route span attributes (§19.2 revised 2026-09-14)
# ---------------------------------------------------------------------------


def build_route_attrs(
    *,
    as_of_receipt: str,
    sub_asks: List[Dict[str, Any]],
    readings_conflict: bool,
    thresholds: Dict[str, float],
    dispatch: str,
    dispatch_rule: str,
    clarify_kind: Optional[str],
    scope_library_version: str,
    scope_choice_ids_with_fact_counts: Dict[str, int],
    reason_codes: List[str],
) -> Dict[str, Any]:
    return {
        "as_of_receipt": as_of_receipt,
        "sub_asks": sub_asks,
        "readings_conflict": readings_conflict,
        "thresholds": thresholds,
        "dispatch": dispatch,
        "dispatch_rule": dispatch_rule,
        "clarify_kind": clarify_kind,
        "scope_library_version": scope_library_version,
        "scope_choice_ids_with_fact_counts": scope_choice_ids_with_fact_counts,
        "reason_codes": reason_codes,
    }


# ---------------------------------------------------------------------------
# plan_validate span attributes
# ---------------------------------------------------------------------------


def build_plan_validate_attrs(
    *,
    task_count: int,
    expanded_tool_calls: int,
    violations: List[Dict[str, Any]],
    gates_reattached: int,
) -> Dict[str, Any]:
    return {
        "task_count": task_count,
        "expanded_tool_calls": expanded_tool_calls,
        "violations": violations,
        "gates_reattached": gates_reattached,
    }


# ---------------------------------------------------------------------------
# handoff span attributes
# ---------------------------------------------------------------------------


def build_handoff_attrs(
    *,
    workflow_id: str,
    reason: str,
    required_count: int,
    remaining_count: int,
    sources_checked_count: int,
    latency_remaining_ms: float,
    violations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "reason": reason,
        "required_count": required_count,
        "remaining_count": remaining_count,
        "sources_checked_count": sources_checked_count,
        "latency_remaining_ms": latency_remaining_ms,
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# materialization_wait span attributes
# ---------------------------------------------------------------------------


def build_materialization_wait_attrs(
    *,
    relevant_doc_count: int,
    wait_ms: float,
    outcome: str,
    physician_choice: Optional[str],
) -> Dict[str, Any]:
    return {
        "relevant_doc_count": relevant_doc_count,
        "wait_ms": wait_ms,
        "outcome": outcome,
        "physician_choice": physician_choice,
    }


# ---------------------------------------------------------------------------
# tool_call span attributes
# ---------------------------------------------------------------------------


def build_tool_call_attrs(
    *,
    invocation_id: str,
    tool_id: str,
    tool_version: str,
    caller: str,
    args_hash: str,
    ok: bool,
    error: Optional[str],
    cache_hit: bool,
    latency_ms: float,
    source_refs: List[str],
    stub: bool,
    gate_required: bool,
    evidence_class: Optional[str],
) -> Dict[str, Any]:
    return {
        "invocation_id": invocation_id,
        "tool_id": tool_id,
        "tool_version": tool_version,
        "caller": caller,
        "args_hash": args_hash,
        "ok": ok,
        "error": error,
        "cache_hit": cache_hit,
        "latency_ms": latency_ms,
        "source_refs": source_refs,
        "stub": stub,
        "gate_required": gate_required,
        "evidence_class": evidence_class,
    }


# ---------------------------------------------------------------------------
# cascade_level span attributes
# ---------------------------------------------------------------------------


def build_cascade_level_attrs(
    *,
    level: int,
    stop: bool,
    stop_rule: Optional[str],
    hits_by_entity: Dict[str, int],
) -> Dict[str, Any]:
    return {
        "level": level,
        "stop": stop,
        "stop_rule": stop_rule,
        "hits_by_entity": hits_by_entity,
    }


# ---------------------------------------------------------------------------
# grounding_check span attributes
# ---------------------------------------------------------------------------


def build_grounding_check_attrs(
    *,
    claims_total: int,
    passed: int,
    failed_by_check: Dict[str, int],
    refused: int,
) -> Dict[str, Any]:
    return {
        "claims_total": claims_total,
        "passed": passed,
        "failed_by_check": failed_by_check,
        "refused": refused,
    }
