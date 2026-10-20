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

---

## Revision 2026-09-30: runtime object model and SDD data-model pass

**Source:** #50 body, sections "Revised 2026-09-26" (T1 checklist) and
"Revised 2026-09-30" (data-model pass); `docs/design/medscribe-runtime-sdd.md`
Appendix A; `docs/design/sdd-issue-alignment.md` parts 1 and 4. The 09-30
list is additive to the 09-26 list, and none of the 09-26 carriers existed on
this branch, so both are applied here; where they differ, 09-30 wins.

### Changes

- `tool_contracts.py`: `SourceKind` = `session_transcript | session_draft | patient_snapshot | document | observation | visit`; `Citation.citation_id` (`make_citation_id()`); `CitationLocator` = `DocumentSpan | TranscriptSpan | RowRef` tagged on `kind` (`document_span`, `transcript_span`, `row_ref`), shape follows `source_kind` and the locator id equals `source_id`; `Claim` / `Derivation` hold `citation_id`s; `claim_citation_closure()`; `IngestLevel`, `RequirementStatus`, `FailureCode`; `RequirementOutcome`, `CoverageBanner`, `EvidenceBundle` with `new_bundle()`, `append_result()`, `close_bundle()`, `source_check_key()`, `bundle_receipt_ids()`; `SCOPE_ARG_KEYS` uses `clinician_id`; `ingest_delta` not assist-callable; `AGENT_ALLOWLIST` deleted; `ContractViolationError`, `BundleClosedError`.
- `intent/schemas.py`: `EvidenceClass` drops `compile`, `doc_ingest`, adds `safety`; `SubAsk.scope_ids`; `TaskSubtype` marked deprecated (G7); `sub_ask_errors()` public for dispatch and `PlanRequest`.
- `intent/executor_contract.py`: deleted `WorkflowState`, `WorkerPlan`, `PlanTask`, `AgentStep`, `validate_agent_step`, `MAX_AGENT_TOOL_CALLS`, `AGENT_WALL_CLOCK_BUDGET_MS`, `ExecutorMode`, `TASK_EXECUTOR_MODE`, `FIXED_TOOL_CHAINS`, `WORKFLOW_NAME`. Added `ReceiptWatermarks`, `AssistRequestContext`, `DispatchDecision`, `PhysicianChoice` (G6), `OutcomeKind`, `WorkflowOutcome` (`Completed | ClarificationNeeded | PlanningNeeded`), `EvidenceRef`, `PlanRequest` (frozen dataclasses), `AnswerStatus`, `AssistAnswer`, `workflow_id_for()`, validators for each. `dispatch_assist(context, slots) -> DispatchDecision`; rule 3 maps to `clarify` and logs `needs_plan`. `ScopeChoice.supporting_citation_ids`.
- `compile_contracts.py`: `FactProvenance`; `CandidateFact.provenance: FactProvenance`; `FactIdentity` drops `source_doc_ids`, `source_segment_ids`; `fact_source_ids()`; `CompileJob.new_doc_ids`; `LaneBOutputs.review_package` deleted; `ReviewState` documented as derived.
- `config.py`: `QUERY_MATERIALIZATION_WAIT_MS` removed; `REFERENCE_RESOLUTION_WAIT_MS` 3000, `RECHECK_INTERVAL_MS` 1000, `POST_BARRIER_RESERVE_MS` 3300.
- Fixtures: `intent_task_v2.jsonl` source kinds mapped (`prior_labs` -> `observation`, `prior_docs` / `uploaded_doc` -> `document`, `prior_visits` -> `visit`), `scope_ids: []` on every sub-ask, `expected_dispatch_rule` added; task-013 relabelled `planning_agent` -> `clarify` (rule 3).
- Contract doc: §1.2 revision list, §2, §3.3–3.4, §4, §5 rewritten (§5.1 workflows by class, §5.2 dispatch with rule and clarify kind, new §5.4 carriers), §6, §7, §8, §9, §10.

### Decisions made here

- Locator tag values `document_span` / `transcript_span` / `row_ref` (SDD gives the field, not the values). Snake case of the type name, so they cannot be confused with `SourceKind` `document`.
- Rule 3 `clarify_kind`: `narrow` for dependent sub-asks, `rephrase` for `no_workflow`. Rule 2: `reading` when readings conflict, else `rephrase` for no class / no sub-asks, else `scope`.
- A sub-ask whose accepted classes are all jobs (`note`, `session_control`) is not underspecified. Found because task-015 ("Generate a discharge summary", label `workflow`) dispatched to `clarify` under the old table too; the label was right, the rule was wrong.
- `PlanRequest` / `EvidenceRef` are frozen dataclasses with tuple fields, because the contract test requires mutation to be rejected; every other carrier stays a TypedDict.
- `ReceiptWatermarks.draft_version` is `Optional[str]`: null before the first compile of a session. SDD shows `str`.
- `RowRef.column` is `Optional[str]`: null means the whole row is the evidence.
- All new types live in the contract modules (`executor_contract.py`, `tool_contracts.py`). SDD A.0 names `assist/outcome.py` and `grounding/answer.py` as the declaring modules for `OutcomeKind` and `AnswerStatus`; those packages land with #56 / #57 and should import from here, not redeclare.

### Non-happy path

| Input | Behavior |
| --- | --- |
| Missing / unknown fields on context, answer, outcome, coverage, clarify, citation | validator returns an error naming the field; operations (`dispatch_assist`, `append_result`, `close_bundle`, `PlanRequest(...)`) raise `ContractViolationError` with field, value, expected |
| Malformed timestamps, naive timestamps, `deadline_at <= as_of_receipt` | rejected by `validate_request_context` / `validate_watermarks` |
| Duplicate: same `citation_id` from two tools | indexed once in the bundle (first wins) |
| Duplicate: same tool and `args_hash` twice | `append_result` returns `False`, logs a warning, result not appended |
| Duplicate: requirement `doc_id`, `scope_ids` entry, cited `citation_id` | rejected |
| Empty: no sub-asks | `clarify` rule 2 `rephrase`; empty bundle closes with empty coverage |
| Empty: `PlanRequest.scope` or `unmet_requirements` | rejected (nothing unmet means `completed`) |
| Single: one workflow | `workflow` rule 4 |
| Oversized: more than `MAX_FANOUT_WORKFLOWS` workflows | `clarify` rule 6 `narrow` |
| Append after close / double close | `BundleClosedError` |
| Scope keys in tool args or a handoff | rejected (`validate_model_tool_args`, `PlanRequest`) |
| Out-of-order sub-ask dependencies / cycles | rejected by `sub_ask_errors` before dispatch |
| Fallback: planner deferred | rule 3 returns `clarify` with `needs_plan` in `reason_codes` and a warning log; visible on the route span |

Upstream failures (timeouts, non-2xx) do not apply: this PR has no I/O.

### Data-model proof

| Type | Field readers (consumer, interface) |
| --- | --- |
| `ReceiptWatermarks` | `as_of_receipt`: retrieval tools (#51, #53), answer; `snapshot_generation`: `get_patient_profile` (#51); `transcript_stream_id`: `retrieve_session` (#51); `draft_version`: note job and compile rebase (#62) |
| `AssistRequestContext` | ids: trace spans (#48); `channel`: dispatch rule 1; `deadline_at`: barrier (T12), workflows (#56); `resumes_answer_id`: UI, replay; `patient_id`, `clinician_id`: registry scope injection (#51), `phi_access_log` |
| `DispatchDecision` | every field: merged `route` span (#48/#55); `dispatch`, `workflow_ids`: executor (#56); `clarify_kind`: scope gate (#83) |
| `EvidenceBundle` | `results`: synthesis, receipts; `citations`: chunk gate, validator (#57); `sources_checked`: dedupe, plan validation; `coverage`: answer coverage line; `closed`: append guard |
| `CoverageBanner` / `RequirementOutcome` | answer coverage line and still-processing card (T12/T13) |
| `WorkflowOutcome` | executor (#56); outcome span |
| `PlanRequest` / `EvidenceRef` | planner when #58 re-enters; returned by fixed workflows in v1 (needs_plan logging) |
| `AssistAnswer` | UI, feedback, follow-ups (`resumes_answer_id`), replay (`bundle_ref`, `grounding`, `watermarks`) |
| `FactProvenance` | review (#61), validator, safety (#60) via `fact_source_ids()` |

Reuse: `FactProvenance.evidence` reuses `Citation` (no `EvidenceSpanRef`);
`EvidenceRef` snapshots bundle ids instead of copying results; `PlanRequest`
reuses `SubAsk` for scope; the answer reuses `ReceiptWatermarks`,
`CoverageBanner`, `ClarifyRequest`, `GroundingReport`. No near-copies.

Not in this revision (named by the SDD, not by the #50 list): `CandidateFact.draft_version`, `SafetyAlertCard.alert_id = item_id`. `server/app/agents/prompts/plan/v1.yaml` on `main` is not on this branch.

### Test criteria (revision)

- [x] `pytest server/tests/unit/test_intent_contract.py -q --override-ini=addopts=` — 706 passed
- [x] `python3 -m compileall -q server/app/agents` — passed
- [x] Contract additions from #50: closed-union exhaustiveness for `WorkflowOutcome`; `PlanRequest` rejects scope keys and mutation; bundle rejects appends after close; `AssistAnswer.cited` equals the closure of its claims
- [x] Golden rows: `dispatch_assist()` on `expected_sub_asks` matches `expected_dispatch` and `expected_dispatch_rule`
- [ ] `pytest server/tests/unit` — 10 files fail to collect in the local venv (`fastapi`, `sqlalchemy` missing); same on the branch before this revision, none import the contract modules
