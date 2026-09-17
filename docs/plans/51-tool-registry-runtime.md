# 51 — shared tool registry runtime + stub tools + safety wrappers

**Issue:** #51
**Parent issue:** #77 (epic: agent refactor, Phases 0–5)
**Sub-issues:** none
**Branch:** `feat/51-tool-registry-runtime` (stacked on `feat/50-runtime-contract-1.2`, PR base is that branch)
**Source docs:** [agent_refactor_plan.md](../agent_refactor_plan.md) §6, §11 Phase 1A items 2–4, §18.2, §18.5;
[copilot-runtime-design.md](../design/copilot-runtime-design.md) tree under `agents/tools/` and `agents/session/`;
[copilot_runtime_first_principles_findings.docx](../design/copilot_runtime_first_principles_findings.docx) §2 items 2, 4, 5, 6 and §8

## Goal

One registry executes every contract 1.2 tool id for all three callers (Lane B
stages, fixed assist workflows, planning agent), injects patient scope the model
can never supply, validates every result against the contract, and writes one
receipt and one `tool_call` span per call. Tool bodies are stubs backed by
fixtures, except the session snapshot and the three safety tools, which are real.

## Alignment with the first-principles findings

| Finding | How this issue honours it |
| ------- | ------------------------- |
| §2.2 information acquisition is a first-class primitive | acquisition is one registry with one contract, not per-caller retrieval code |
| §2.5 received vs materialized vs authorized | stub fixtures carry `evidence_state` per citation, including an in-flight document in `received` |
| §2.6 receipt time separate from observation time | citations carry both `received_at` and `observed_at` |
| §8 evidence and provenance as first-class data | `requires_citations` is enforced at the registry boundary, so an ungrounded ok result cannot leave a tool |
| §2.13 human authority is a separate axis | registry refuses any tool whose spec writes outside `session_scratch` / `session_draft`; no PostgreSQL writes |

## Scope

In scope:

- `agents/tools/registry.py` — lookup, caller permission, scope injection, arg and result validation, receipts, spans
- `agents/tools/runner.py` — parallel groups, one SQLAlchemy session per call
- `agents/tools/stubs.py` + `tests/fixtures/tool_results/` — a stub per tool id, five cases
- `agents/tools/safety.py` — `check_med_conflicts`, `check_dosage`, `check_metric_alerts` over the existing engines
- `agents/session/snapshot.py` — real `PatientContextSnapshot` load, cache, invalidation (§6)
- `nodes/load_patient_context.py` — reads through the snapshot
- `nodes/clinical_suggestions.py` — Lane B call site; calls the three safety tools through the registry
- Retirements: `tools/tool_universe.py`, `tool_universe.yaml`, `tools/patient_lookup.py`

Out of scope:

- Real retrieval backends (Phase 1B, #53 / #54) — stubs stand in, with `stub: true` on the span
- Real compute tools (#85) — registered as stubs only
- Versioned safety rule contract (#60) — wrappers use the engines unchanged
- LLM adapters, greeting removal (#52); assist graph (#56); grounding validator (#57)
- Receipt ledger and `as_of_receipt` filtering (#84) — snapshot carries `loaded_at` only

## Decisions taken with the user (2026-09-17)

1. `stub: true` lives on the `tool_call` span attributes (already defined by #48) and on the
   `controls.trace_log` entry. `ToolInvocationReceipt` stays exactly as contract 1.2 froze it.
2. `get_patient_profile` is real, backed by the session snapshot (§18.2, §6). Every other
   retrieval, ingest, compare, note and compute tool is a stub.
3. `tool_universe.py` / `.yaml` and `patient_lookup.py` are retired here, per the design tree.
   `clinical_suggestions_node` moves onto the registry's safety tools in the same PR.
4. The branch is stacked on PR #88 (#50) because contract 1.2 has not merged yet. The PR is
   retargeted to `main` once #88 lands.

## Steps

1. Plan doc (this file), committed first.
2. `agents/tools/errors.py` + `registry.py`: `ToolScope`, `ToolHandler`, `ToolRegistry.call()`,
   caller permission rules from `TOOL_SPECS`, `validate_model_tool_args` on model-proposed args,
   `validate_tool_result` on every result, receipt to `controls.trace_log`, `tool_call` span
   via `build_tool_call_attrs`.
3. `agents/tools/runner.py`: `run_parallel_group()` on a thread pool, one SQLAlchemy session per
   call from `AgentContext.db_session_factory`, closed in `finally`; failures are per-call, never
   group-wide.
4. `tests/fixtures/tool_results/*.json` + `agents/tools/stubs.py`: one fixture file per tool id
   with cases `ok`, `empty`, `no_source`, `in_flight_doc`, `chart_vs_session_conflict`;
   `register_stub_tools(registry, case="ok")`.
5. `agents/session/snapshot.py`: `PatientContextSnapshot`, `SnapshotStore` (Redis with in-process
   fallback, same pattern as `core/review_queue.py`), `load_snapshot()`, `invalidate()`.
6. `agents/tools/profile.py` handler for `get_patient_profile` over the snapshot, registered real.
7. `agents/tools/safety.py`: the three wrappers, `not_covered[]` from table coverage,
   `NOT_COVERED_ERROR` when nothing in the request is covered.
8. Call sites: `load_patient_context_node` reads the snapshot; `clinical_suggestions_node` calls
   the three safety tools through the registry as `caller="lane_b_stage"`,
   `caller_ref="safety_and_validate"`.
9. Retire `tool_universe.py`, `tool_universe.yaml`, `patient_lookup.py`; update
   `agents/tools/__init__.py`, `agents/config.py` (`tool_universe_service` dropped), and
   `tests/unit/test_diagnostic_intelligence.py`.
10. Tests: `tests/unit/test_tool_registry.py`, `test_tool_runner.py`, `test_tool_stubs.py`,
    `test_safety_tools.py`, `test_session_snapshot.py`, `test_tool_call_sites.py` (the two exit
    call sites end to end); rewrite the ToolUniverse half of `test_diagnostic_intelligence.py`.

## Data models and ephemeral state

Reuse first: `ToolResult`, `ToolInvocationReceipt`, `Citation`, `CitationLocator`, `ToolSpec` and
`EvidenceState` all come from `agents/tool_contracts.py` (contract 1.2) unchanged. Spans reuse
`build_tool_call_attrs` from #48. Redis access copies the `core/review_queue.py` pattern rather
than adding a client abstraction.

Two new objects, both ephemeral, neither persisted to PostgreSQL:

`ToolScope` — runtime-injected identity, one per call.

| Field | Consumer | Interface crossed |
| ----- | -------- | ----------------- |
| `patient_id` | every retrieval and safety handler | registry → handler |
| `session_id` | receipt `session_id`, snapshot cache key | registry → receipt, snapshot store |
| `tenant_id` | snapshot cache key, future row filters | registry → handler |
| `doctor_id` | note and draft-writing handlers | registry → handler |

No other field is added: the set is exactly `SCOPE_ARG_KEYS` from the contract, so the keys a
model may not supply and the keys the runtime injects cannot drift apart.

`PatientContextSnapshot` — plan §6.1, stored under the session key.

| Field | Consumer | Interface crossed |
| ----- | -------- | ----------------- |
| `patient_id`, `tenant_id` | cache key, scope check on read | store → loader |
| `version` | `get_patient_profile` citation, invalidation check | tool → citation |
| `demographics`, `allergies`, `medications`, `problems` | safety tools, `get_patient_profile` sections | snapshot → tools |
| `recent_labs_summary`, `recent_visits_index` | `get_patient_profile` sections | snapshot → tools |
| `retrieval_keys` | Lane B `patient_record_fields`, later `retrieve_structured` scoping | snapshot → node |
| `loaded_at` | TTL expiry, `Citation.received_at` for profile citations | store → tool |
| `source` | logs and the `cache_hit` receipt flag | store → registry |

`embedding_handles` from §6.1 is folded into `retrieval_keys`; shipping both would be two names
for one concept. No field is added "for later": #84 adds the receipt ledger as its own object
rather than growing this one.

## Non-happy paths

| Case | Behaviour |
| ---- | --------- |
| Unknown tool id | `UnknownToolError`, no span, nothing executed |
| Caller not permitted (planner calls `check_dosage`; Lane B stage not in `lane_b_stages`) | `ToolPermissionError`, refusal logged at `warning`, span `status="error"` |
| Model args carry `patient_id` or another scope key | `ToolArgumentError` naming the dotted paths; call never runs |
| Handler raises | caught, `ok=False`, `error="handler_error"`, span `status="error"`, exception logged with tool id and invocation id; no exception escapes into the graph |
| Handler returns a contract-invalid result | `ToolResultContractError`; the invalid result is never returned to the caller |
| Empty result set | `ok=True`, empty data, no citations — allowed only when `requires_citations` is false, otherwise the `no_source` case with `ok=False` |
| Redis missing or down | snapshot falls back to the in-process cache, logged once at `warning`; loads still succeed |
| Snapshot load fails (no repos, DB error) | empty snapshot, `loaded_from_db=False`, warning; `get_patient_profile` returns `no_source` rather than inventing a profile |
| Safety engine raises or lacks a table | that check joins `not_covered[]` with its reason; other checks still run; all three uncovered returns `ok=False, error="not_covered"` |
| Parallel group: one call fails or times out | its own failed `ToolResult`, siblings unaffected, group returns in request order |
| Duplicate or concurrent snapshot load | single-flight per key; second caller gets the cached value and `cache_hit=True` |

Logging rule: ids, counts, sizes and durations only. No transcript text, no fixture payloads, no
patient fields in any log line.

## Test criteria

Commands (run from `server/`, with `-o addopts=""` because this machine has no
`pytest-cov`):

- `python3 -m pytest tests/unit/test_tool_registry.py tests/unit/test_tool_runner.py tests/unit/test_tool_stubs.py tests/unit/test_safety_tools.py tests/unit/test_session_snapshot.py tests/unit/test_tool_call_sites.py -q` — 122 passed
- `python3 -m pytest tests/unit/test_diagnostic_intelligence.py -q` — 69 passed, 5 failed, all 5 failing identically at the branch point (`langgraph` is not installed here)
- `python3 -m pytest tests/unit -q` against the branch point — same 43 failures and 26 collection errors as the baseline, 772 → 915 passing
- `python3 -m pytest evals -q` — 40 passed, unchanged

Environment limits (pre-existing, not introduced here): this machine's venv has
no `sqlalchemy`, `langgraph`, `yaml`, or `requests`, so 10 unit modules and 4
modules under `tests/` cannot be collected at all, on this branch and at the
branch point alike. Every comparison above is against a baseline run of the same
commands in a worktree at the branch point.

Acceptance (from the issue):

- [ ] Registry does lookup, scope injection, `validate_model_tool_args`, `ToolResult` validation, and writes receipts to `controls.trace_log` plus `tool_call` spans
- [ ] Parallel group runner uses a thread pool with one SQLAlchemy session per call
- [ ] Every §18.2 tool id has a stub from `tests/fixtures/tool_results/`, covering ok, empty, `no_source`, in-flight doc, and chart-vs-session conflict; receipts flag `stub: true`
- [ ] Real session snapshot loader with §6.2 invalidation
- [ ] Three safety tools wrap `ClinicalSuggestionEngine`, `DosageCalculator`, `LabInterpreter`
- [ ] Exit: registry used by one assist and one Lane B call site in tests
- [ ] Exit: scope-key and disallowed-tool traps rejected
- [ ] Exit: snapshot cache hit on second compile

## Risks and open questions

- Stacked on unmerged PR #88. If contract 1.2 changes in review, this branch rebases onto the
  updated #50 branch before its own review.
- `clinical_suggestions_node` output shape changes: `suggestions["tool_universe"]` becomes
  `suggestions["safety_tools"]`. The node is not in another workstream's ownership list, but the
  key rename is called out in the PR so Lane B work (#61) expects it.
- The dosage wrapper depends on `check_renal_dosing` / `check_geriatric_appropriateness`, which
  `DosageCalculator` may not define. Missing methods are reported as `not_covered`, not as errors.
