# 48 — trace contract, sinks, and prompt registry (Phase 0.5a)

**Issue:** #48
**Parent issue:** #77 (epic: agent refactor Phases 0–5)
**Sub-issues:** none
**Branch:** `feat/48-trace-contracts-sinks-prompt-registry`
**Source docs:** agent_refactor_plan.md §11 Phase 0.5 items 1–3, §19.2–§19.3; docs/design/copilot-runtime-design.md

## Goal

Deliver the trace contract types, sinks, and prompt registry that every later Phase 0.5–5 component depends on for logging, metrics, and prompt versioning. A stub run must write a JSONL trace; the PHI scanner L1 test must fail on a planted fixture.

## Scope

In scope:
- `agents/trace_contracts.py`: `TRACE_SCHEMA_VERSION`, `SpanKind`, `TraceSpan`, `FeedbackEvent`
- `agents/tracing/spans.py`: PHI-free span attribute helpers
- `agents/tracing/sinks.py`: `TraceSink` protocol, `JsonlTraceSink`, `PostgresTraceSink` (interface only), `PrometheusMetrics`
- `agents/prompts/registry.py`: `PromptRegistry` loading `prompts/<id>/v<N>.yaml`
- 6 placeholder YAML prompts: `slot_extract`, `scope_render`, `plan`, `synthesis`, `judge`, `addressee`
- `app/logging.py`: wire `JsonlTraceSink` at startup
- `app/monitoring.py`: dispatch/wait/handoff/guardrail Prometheus metric definitions
- `database/models.py`: `AgentTraceSpan` SQLAlchemy model
- `migrations/versions/<rev>_agent_trace_spans.py`: Alembic migration
- `evals/deterministic/test_trace_schema.py`: L1 TraceSpan schema + JSONL round-trip
- `evals/deterministic/test_phi_scanner.py`: PHI scanner fails on planted name/MRN/lab

Out of scope:
- `PostgresTraceSink` full implementation (lands in a later issue with the migration)
- Real model calls from prompts (placeholders only here)
- L2/L3 eval suites (#49)
- `tool_contracts.py` 1.2 tool ids (#50)

## Steps

1. Create `server/app/agents/trace_contracts.py` — all types from §19.2
2. Create `server/app/agents/tracing/__init__.py`, `spans.py`, `sinks.py`
3. Create `server/app/agents/prompts/__init__.py`, `registry.py`
4. Create 6 placeholder YAML prompts in `server/app/agents/prompts/<id>/v1.yaml`
5. Update `server/app/logging.py` — wire `JsonlTraceSink`
6. Update `server/app/monitoring.py` — add metric definitions
7. Update `server/app/database/models.py` — add `AgentTraceSpan`
8. Create Alembic migration for `agent_trace_spans`
9. Create `server/evals/__init__.py`, `server/evals/deterministic/__init__.py`
10. Write `evals/deterministic/test_trace_schema.py` and `test_phi_scanner.py`
11. Run `pytest server/evals/deterministic/ -v`

## Test criteria

Commands:
- `pytest server/evals/deterministic/ -v` passes (trace schema) and fails on PHI fixture

Acceptance (from the issue):
- [ ] `agents/trace_contracts.py` defines `TraceSpan`, span kinds, required attributes, `feedback.submitted`, `TRACE_SCHEMA_VERSION`
- [ ] `route` span attributes per §19.2 (revised 2026-09-14): `sub_asks`, `readings_conflict`, thresholds, `dispatch`, `dispatch_rule`, `reason_codes`
- [ ] `TraceSink` protocol + `JsonlTraceSink` + Prometheus metrics; `PostgresTraceSink` interface only
- [ ] `PromptRegistry` + placeholder prompts at `agents/prompts/<id>/v1.yaml`
- [ ] PHI scanner test fails on planted fixture name/MRN/lab value
- [ ] Stub run writes a readable JSONL trace (Phase 0.5 exit criterion)

## Risks and open questions

- `PostgresTraceSink` full implementation requires the `agent_trace_spans` migration to be applied; the interface-only stub sidesteps this for now.
- `PrometheusMetrics` definitions here are registration only; real counter increments land per-node in Phase 1A.
- Prompt YAML `input_schema`/`output_schema` are placeholder stubs; they get typed in when each prompt's code path moves onto the registry.
