# Issue #37 -- Dynamic LLM Routing and Cost Optimization

**Title:** feat(llm): add dynamic routing and cost-aware provider selection

**Phase:** 5 (Dynamic LLM Routing + Cost Optimization) -- Steps 20-22

**Resume bullets served:** V1#2 (dynamic routing between local GPU and cloud APIs)

---

## Overview

Add a routing layer to dynamically select LLM providers based on latency, cost, and reliability. Includes integration of local vLLM inference as an additional provider and per-call cost tracking.

## Goals

- Optimize for latency and/or cost per request based on configurable strategy
- Enable fallback across providers on failure
- Support both local (vLLM) and cloud inference backends
- Track per-call costs for budget management

## Scope

- Directory: `services/api/llm/`
- Extends the multi-provider dispatch system from Issue #30

## Tasks

### vLLM Local Inference Backend (Step 20)
- [ ] Add `vllm.go` provider in `services/api/llm/`:
  - [ ] vLLM exposes OpenAI-compatible `/v1/chat/completions` API
  - [ ] Reuse existing `openaiCompatibleClient` struct with different `base_url`
  - [ ] New environment variable: `VLLM_ENDPOINT` (e.g., `http://vllm:8000`)
  - [ ] Health check: verify vLLM endpoint is reachable before routing requests
  - [ ] Model availability detection: query vLLM `/v1/models` endpoint

### Routing Optimizer (Step 21)
- [ ] Implement `services/api/llm/router.go`:
  - [ ] Maintain per-provider rolling metrics:
    - [ ] p50 latency (exponential weighted moving average)
    - [ ] Error rate (sliding window, e.g., last 100 requests)
    - [ ] Availability status (up/down based on recent errors)
  - [ ] Implement routing strategies:
    - [ ] `latency_first` -- select provider with lowest p50 latency
    - [ ] `cost_first` -- select provider with lowest cost-per-token estimate
    - [ ] `balanced` -- weighted score combining latency and cost
  - [ ] Strategy selection via configuration: `LLM_ROUTING_STRATEGY` environment variable
  - [ ] Implement provider selection logic:
    - [ ] Filter available providers (API key set + healthy)
    - [ ] Rank by strategy score
    - [ ] Select top-ranked provider
  - [ ] Implement fallback mechanism:
    - [ ] On provider failure, try next in ranked list
    - [ ] Mark failed provider as unhealthy for cooldown period
    - [ ] Circuit breaker pattern: open after N consecutive failures, half-open after cooldown
  - [ ] Replace static priority chain from registry.py

### Cost Tracking (Step 22)
- [ ] Define cost-per-token estimates per provider/model:
  - [ ] Configurable via environment or config file
  - [ ] Default estimates for common models (GPT-4, Claude, Llama, Gemini)
- [ ] Emit per-call metrics as Prometheus metrics:
  - [ ] `llm_prompt_tokens_total` (counter, labels: provider, model)
  - [ ] `llm_completion_tokens_total` (counter, labels: provider, model)
  - [ ] `llm_request_latency_seconds` (histogram, labels: provider, model)
  - [ ] `llm_estimated_cost_usd` (counter, labels: provider, model)
  - [ ] `llm_routing_decisions_total` (counter, labels: strategy, selected_provider)
- [ ] Optionally persist to `llm_call_log` PostgreSQL table:
  - [ ] Columns: `id`, `session_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `estimated_cost_usd`, `status`, `created_at`
  - [ ] Enable/disable via `LLM_CALL_LOGGING` environment variable

## Acceptance Criteria

- LLM requests route to vLLM when available and healthy, fall back to cloud providers
- Routing strategy correctly selects provider based on configured criteria
- Cost log shows per-call cost estimates
- Failures trigger fallback to secondary providers
- Metrics accurately reflect routing decisions and provider performance
- Circuit breaker prevents repeated calls to failing providers

## Implementation Notes

- Use exponential weighted moving average for latency tracking (alpha = 0.1 gives good smoothing)
- Keep routing logic stateless where possible: per-provider metrics are atomic counters updated after each call
- Reuse OpenAI-compatible client for vLLM (same request/response format)
- Cost estimates are approximations based on published pricing; they do not need to be exact
- The router wraps the existing `Registry` from Issue #30: registry handles provider creation, router handles selection

## Files to Create

```
services/api/llm/
  vllm.go          -- vLLM provider (reuses openaiCompatibleClient)
  router.go        -- Routing optimizer with strategies and circuit breaker
  cost.go          -- Cost-per-token configuration and tracking
```
