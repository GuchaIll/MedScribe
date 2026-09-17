# 50 — runtime contract 1.2 PR (Phase 1A item 1)

**Issue:** #50
**Parent issue:** #77
**Sub-issues:** none
**Branch:** `feat/50-runtime-contract-1.2`
**Source docs:** `docs/copilot_runtime_contract.md` §12; `docs/agent_refactor_plan.md` §18.2, §18.6, §20; `docs/design/copilot-runtime-design.md`

## Goal

Bump the copilot runtime contract from 1.1 to 1.2. All contract types, dispatch
logic, and provisional numbers land in code before any Phase 1 implementation
issue (#51–#63) can import them. Contract tests pass at 1.2.

## Scope

In scope:
- `tool_contracts.py`: tool id v2 rename/split/add, `Citation` adds `received_at` / `evidence_state` / `locator`, new `Claim` + `Derivation` types, `ToolCaller` `bounded_agent` → `planning_agent`, `RUNTIME_CONTRACT_VERSION` → `"1.2"`
- `agents/config.py`: new provisional constants `SUB_ASK_MIN_CONFIDENCE`, `MAX_FANOUT_WORKFLOWS`, `QUERY_MATERIALIZATION_WAIT_MS`
- `intent/schemas.py`: `EvidenceClass` literal, `SubAsk` TypedDict, `TaskSlots.sub_asks` + `TaskSlots.readings_conflict`
- `intent/executor_contract.py`: `ExecutorMode` `fixed | planning_agent`, `DispatchValue`, `dispatch_assist()` pure function, `ClarifyKind`, `ScopeChoice`, `ClarifyRequest`, `PlanTask`, `WorkerPlan`, `WorkflowState`; import provisional constants from config
- `server/tests/fixtures/`: create directory; add `intent_task_v2.jsonl` (renamed from v1 with new fields) and `intent_addressee_v1.jsonl`
- `server/tests/unit/test_intent_contract.py`: update all frozen-enum assertions and golden set references for 1.2
- `docs/copilot_runtime_contract.md`: integrate §12 into §1–§9, bump version badge, retire §12 pending marker

Out of scope:
- `dispatch.py`, `stage_b.py` live implementations (#55)
- `WorkerPlan` planner runtime (#58)
- Scope library + `ScopeChoice` generation (#83)
- Compute tools implementation (#85)
- Receipt ledger (#84)
- `intent_addressee_v2.jsonl` rename (#63)
- Any route or graph changes

## Steps

1. Create branch `feat/50-runtime-contract-1.2` off `origin/main` (done)
2. Write this plan doc; commit as first commit
3. Add provisional constants to `agents/config.py`
4. Update `tool_contracts.py`: new ToolId, EvidenceState, Citation, Claim, Derivation, ToolSpec entries, ToolCaller, version
5. Update `intent/schemas.py`: EvidenceClass, SubAsk, TaskSlots v2
6. Update `intent/executor_contract.py`: ExecutorMode, DispatchValue, dispatch_assist(), ClarifyRequest, ScopeChoice, WorkerPlan, PlanTask, WorkflowState
7. Create `server/tests/fixtures/intent_task_v2.jsonl` (20+ rows with expected_sub_asks, expected_dispatch)
8. Create `server/tests/fixtures/intent_addressee_v1.jsonl` (15+ rows)
9. Update `test_intent_contract.py` for 1.2
10. Update contract doc: version, status, inline §12 into §1–§9
11. Run `pytest server/tests/unit/test_intent_contract.py -v`; fix failures
12. Push branch; open PR

## Test criteria

Commands:
- [x] `pytest server/tests/unit/test_intent_contract.py -q --override-ini=addopts=` — 577 passed
- [x] `python3 -m compileall -q server/app/agents` — passed

Acceptance (from issue):
- [x] `tool_contracts.py`: `retrieve_structured`, `get_patient_profile`, `retrieve_source_chunks`; safety tools split; compute tools added; `ToolCaller` uses `planning_agent`
- [x] `tool_contracts.py`: `Citation.received_at`, `evidence_state`, source-specific locator validation; structured `Claim.derivation`
- [x] `intent/schemas.py`: `SubAsk`, `TaskSlots.sub_asks`, `readings_conflict`, `evidence_class`, nested validation
- [x] `executor_contract.py`: modes `fixed | planning_agent`; workflow-count dispatch table; `WorkerPlan` / `PlanTask` with `needs_scope`; `ClarifyRequest`; `WorkflowState`; provisional constants imported from config
- [x] `RUNTIME_CONTRACT_VERSION == "1.2"`, contract tests pass

## Risks and open questions

- `intent_addressee_v1.jsonl` is referenced by existing tests but did not exist on main; this PR creates it (65-row blocker)
- Provisional numbers in config.py; test imports them from there via executor_contract re-exports
- §12 of the contract doc becomes normative when this PR lands; keep the §12 section but label it "migration notes / history"
- Review follow-up: dispatch counts accepted workflows (not just sub-asks); nested
  intent/tool-result validators reject malformed payloads; planner, grounding,
  and Lane B typed models match the source contract before runtime consumers land.
