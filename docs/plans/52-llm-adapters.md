# 52 — LLM adapters, drop LangChain, remove greeting node (Phase 1A item 5)

**Issue:** #52
**Parent issue:** #77
**Sub-issues:** none
**Branch:** `feat/52-llm-adapters`
**Source docs:** agent_refactor_plan.md §11 Phase 1A item 5, §18.1, §18.11; copilot-runtime-design.md (models/ section)

## Goal

`LLMAdapter` protocol with `OpenAICompatibleAdapter`, `AnthropicAdapter`, and `StubAdapter`;
per-role model config (`LLM_ROLE_*` env vars); `BudgetAwareLLMAdapter` that wraps any
adapter with per-run call-capping; drop `langchain` from requirements; feature-flag
`greeting` node removal; every adapter call emits an LLM span.

## Scope

In scope:
- `LLMAdapter` protocol + `ToolCallProposal` type in `server/app/models/llm.py`
- `server/app/models/adapters/` package: `openai_compat.py`, `anthropic.py`, `stub.py`
- Per-role config: `load_adapter_for_role(role)` reading `LLM_ROLE_<ROLE>=provider:model`
- `BudgetAwareLLMAdapter` in `server/app/agents/tools/llm.py` — wraps any `LLMAdapter`
  with `BudgetGuardrail`; replaces old `LLMTool`/`LLMClient` pairing; old `LLMClient`
  kept as compat shim pointing at the role-less default adapter
- Remove `langchain==0.2.17` pin from `requirements.docker.txt`; keep `langchain-core`
  (LangGraph dependency); bump `openai>=1.40`, `anthropic>=0.25`
- Feature-flag `greeting` node: env var `ENABLE_GREETING_NODE=1` (default off);
  both `graph.py` and `pipeline_progress.py` gate on it; frontend catalogue unchanged
  (client-side flag is out of scope, noted in open questions)
- LLM span emitted on every adapter call via `build_llm_attrs` + `TraceSpan` from #48
- Unit tests: adapter protocol contract, budget-wrapping, role-config loading

Out of scope:
- Lane B `enrich` wiring to registry (#61 / #51 dependency)
- `agents/tools/llm.py` retirement — file kept; `LLMTool` is replaced by
  `BudgetAwareLLMAdapter` but both names are exported during transition
- Frontend node-catalogue greeting flag (client/v2; separate issue)
- Groq `llama-4-scout` availability verification (CI step, not code)
- PHI provider restriction enforcement (runtime config policy, not adapter code)

## Steps

1. Add `ToolCallProposal` + `LLMRole` + `LLMAdapter` protocol to
   `server/app/models/llm.py`; add `load_adapter_for_role(role)` factory; keep
   `LLMClient` as compat shim (`generate_response` delegates to default adapter's
   `generate`).
2. Create `server/app/models/adapters/__init__.py` re-exporting all three adapters.
3. Create `openai_compat.py`: `OpenAICompatibleAdapter` — uses `openai>=1.40` client;
   implements all three protocol methods; emits LLM span in each method.
4. Create `anthropic.py`: `AnthropicAdapter` — uses `anthropic>=0.25`; same methods
   and span emission.
5. Create `stub.py`: `StubAdapter` — scripted responses/plans/tool calls from
   constructor args; zero network; used by tests and 1A stubs.
6. Rewrite `server/app/agents/tools/llm.py` as `BudgetAwareLLMAdapter`; takes any
   `LLMAdapter` + `BudgetGuardrail`; delegates all three methods; raises
   `BudgetExhaustedError` before calling if cap hit; export old name `LLMTool` as
   alias for backward compat.
7. Feature-flag greeting: `graph.py` wraps greeting node registration + edges in
   `if os.getenv("ENABLE_GREETING_NODE"):`; `pipeline_progress.py` gates the stage
   entry on the same env var.
8. `requirements.docker.txt`: remove `langchain==0.2.17`; bump `openai` to `>=1.40,<2`;
   bump `anthropic` to `>=0.25,<1`.
9. Add `server/tests/unit/test_llm_adapters.py`: protocol-compliance tests via
   `StubAdapter`; budget-capping test; role-config test; greeting-flag test.

## Test criteria

Commands:
- `cd server && python -m pytest tests/unit/test_llm_adapters.py -v` — all pass
- `cd server && python -m pytest tests/unit/ -v --ignore=tests/unit/test_llm_adapters.py` — no regressions
- `cd server && python -c "from app.models.adapters import OpenAICompatibleAdapter, AnthropicAdapter, StubAdapter; print('adapters import ok')"` — passes without network

Acceptance (from issue):
- [ ] `LLMAdapter` protocol: `generate`, `generate_structured`, `generate_with_tools`
- [ ] `OpenAICompatibleAdapter`, `AnthropicAdapter`, `StubAdapter`
- [ ] Per-role model config (`LLM_ROLE_ROUTER=...`)
- [ ] Bump `openai` / `anthropic` pins; remove `langchain` pin
- [ ] Feature-flag `greeting` node removal (ENABLE_GREETING_NODE)
- [ ] Every adapter call emits an LLM span
- [ ] Registry default `llama-4-scout` verified (manual; noted in PR)

## Risks and open questions

- `langchain-core` must remain because `langgraph` depends on it. Only `langchain`
  (the full meta-package) is dropped.
- `LLMClient` compat shim means existing callers (`summarizer.py`, `nodes/clean.py`,
  `agents/config.py`) are unaffected; migration to `BudgetAwareLLMAdapter` is
  incremental and belongs to the workflow issues (#56, #58, #61).
- Greeting flag default is OFF. If any integration test or fixture relies on
  `greeting` being in the graph, those tests must be updated. Known tests in
  `test_pipeline_progress.py` reference `greeting` by name but test the progress
  store, not graph topology — they are unaffected.
- Frontend pipelineNodes.ts still lists `greeting` — it should be gated by the same
  env var exposed to the client. Flagged as open question, out of scope here.
- OpenRouter must not receive real PHI (`AnthropicAdapter`/`OpenAICompatibleAdapter`
  both carry a `_baa_safe` flag checked before construction; enforcement is a
  configuration policy, not adapter code).

## Non-happy path

- Missing `LLM_ROLE_*` env var: `load_adapter_for_role` falls back to the legacy
  `get_llm_client()` path (logged at `warning`).
- Unknown `provider:` prefix in role env: raises `LLMConfigError` (new project error
  type) with field name, received value, and supported providers.
- `BudgetAwareLLMAdapter` with budget exhausted: raises `BudgetExhaustedError`
  before the network call; caller receives the error (not a silent empty string).
- Adapter network failure (timeout, 5xx): underlying SDK exception propagates; the
  caller (node or workflow) handles retries — adapters do not swallow exceptions.
- `StubAdapter` called with no scripted response for a call index: raises
  `StubAdapter.Exhausted` so test authors see the over-call explicitly.

## Data models and ephemeral state

### `ToolCallProposal`
- `tool_name: str` — read by planner runner (#58), grounding validator (#57)
- `tool_args: dict` — read by runner
- `tool_call_id: str` — correlates proposal to receipt, read by runner

No new persistent fields. `ToolCallProposal` is in-memory only; it is not persisted to PostgreSQL.

### `LLMAdapter` protocol
Stateless structural protocol (no `__init__` signature). Each concrete adapter holds:
- `_client` — SDK client; constructor arg; not serialised
- `_model: str` — read by span builder
- `_provider: str` — read by span builder
- `_role: str` — read by span builder and by tests

### Per-role config
`LLM_ROLE_<ROLE>` → `"<provider>:<model_name>"`. Role names match the `SpanKind` roles
in the trace contracts (`router`, `planner`, `synthesis`, `judge`, `addressee`).
No new DB or Redis state.

## Self-review

- Validation: LLMConfigError raised on missing api_key, empty model name, bad
  LLM_ROLE_* format, unknown provider. BudgetExhaustedError before any network call.
  ValueError on empty messages/tools/prompt in every public method.
  StubAdapter.Exhausted on over-call.
- Logging: every adapter logs at DEBUG on construction and per-call token counts.
  Every caught exception logged with context (role, model). Budget fallback warns.
  Span emission failures logged at ERROR (non-fatal). Budget-exhausted try_generate
  warns at WARNING.
- Non-happy path: missing env var falls back with warning; bad format raises;
  unknown provider raises; api key missing raises; BudgetExhaustedError raised
  before network call when cap is hit; generate_structured repair retry on
  validation failure, raises ValueError on second failure; StubAdapter.Exhausted
  on empty queue; LLMTool.try_generate catches all exceptions and returns fallback.
- Data models: ToolCallProposal is a new in-memory-only type (not persisted);
  necessity per field: tool_name (runner uses it), tool_args (runner uses it),
  tool_call_id (correlates to receipt, validator uses it). LLMAdapter is a
  structural protocol, no new persistent fields. No new DB/Redis state.
