# docs — track planning docs and Phase 0 contract code

**Issue:** none (prerequisite for issues #47–#81, which link to these docs)
**Parent issue:** none
**Sub-issues:** none
**Branch:** `docs/track-planning-docs`
**Source docs:** the files being committed

## Goal

The planning docs and Phase 0 runtime contract code that issues #47–#81 reference exist on `main`, so issue links resolve and later phases build on tracked code.

## Scope

In scope:
- Planning docs: `docs/agent_refactor_plan.md`, `docs/agentic_design.md`, `docs/copilot_runtime_contract.md`, `docs/demo_deployment.md`, `docs/revision_plan.md`, `docs/todo_list.md`, `docs/v2_integration_plan.md`, `docs/whisper_pyannote_role_detection_plan.md`, `docs/whisperwave_integration.md`
- Benchmark artifacts: `docs/benchmarks/full-pipeline/*`, `docs/benchmarks/gateway-ingestion-qps/*`
- Phase 0 contract code: `server/app/agents/intent/`, `server/app/agents/tool_contracts.py`, `server/app/agents/compile_contracts.py`
- Golden sets and tests: `server/tests/fixtures/intent_*_v1.jsonl`, `server/tests/unit/test_intent_contract.py`

Out of scope:
- `distributed_plan.md`, `distributed_plan2.md` (superseded)
- `docs/orchestrator_worker.md` (third-party course notes, not a project doc)
- `practice.ts`, `client/v2/bun.lockb`
- Uncommitted edits to `.github/copilot-instructions.md`, `docs/api/assistant.md`, `docs/api/session.md`
- Wiring the contract code into routes or `graph.py` (issues #50, #51)

## Steps

1. Branch from `origin/main`
2. Stage only the in-scope paths
3. Run the contract tests
4. Commit, push, open PR

## Test criteria

Commands:
- `pytest server/tests/unit/test_intent_contract.py` passes

Acceptance:
- [ ] Only in-scope paths in the diff
- [ ] Nothing imports the new modules from routes or `graph.py` (contract code stays inert)

## Risks and open questions

- Some docs describe state that has since changed (for example node counts); #74 and #75 track those fixes.
