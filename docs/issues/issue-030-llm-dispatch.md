# Issue #30 -- Multi-Provider LLM Dispatch System

**Title:** feat(llm): implement multi-provider LLM dispatch system

**Phase:** 1 (Go API Gateway + Orchestrator Core) -- Step 6

**Resume bullets served:** V1#2 (dynamic routing between local GPU and cloud APIs)

---

## Overview

Port the Python LLM provider factory pattern (`llm_providers.py`, `llm.py`, `registry.py`) to Go. Each provider is a Go struct implementing the `LLMClient` interface with HTTP calls to the respective API. This is the foundational dispatch layer used by all LLM-calling pipeline nodes.

## Goals

- Support all existing LLM providers (Groq, OpenAI, Anthropic, Google, OpenRouter)
- Maintain the multi-provider priority/fallback logic from `registry.py`
- Enable addition of new providers with minimal code changes
- Provide consistent error handling, retry logic, and token usage tracking

## Scope

- Directory: `services/api/llm/`
- Replaces:
  - `llm.py` (LLM client abstraction)
  - `llm_providers.py` (provider factory and implementations)
  - `registry.py` (multi-provider priority chain)

## Tasks

### LLMClient Interface
- [ ] Define `LLMClient` interface:
  ```
  type LLMClient interface {
      Generate(ctx context.Context, prompt, systemPrompt string, opts Options) (string, TokenUsage, error)
  }
  ```
- [ ] Define `Options` struct: model name, temperature, max tokens, top_p, response format
- [ ] Define `TokenUsage` struct: prompt tokens, completion tokens, total tokens

### Provider Implementations
- [ ] `groq.go` -- Groq API client (OpenAI-compatible HTTP contract):
  - Base URL: `https://api.groq.com/openai/v1/chat/completions`
  - Default model: `llama-3.3-70b-versatile`
  - Auth: Bearer token from `GROQ_API_KEY`
- [ ] `openai.go` -- OpenAI API client:
  - Base URL: `https://api.openai.com/v1/chat/completions`
  - Auth: Bearer token from `OPENAI_API_KEY`
  - Shared HTTP contract with Groq and OpenRouter
- [ ] `anthropic.go` -- Anthropic API client:
  - Base URL: `https://api.anthropic.com/v1/messages`
  - Distinct request shape: `messages` array with `role`/`content`, `system` as top-level field
  - Auth: `x-api-key` header from `ANTHROPIC_API_KEY`
  - Response parsing differs from OpenAI format
- [ ] `google.go` -- Google Gemini API client:
  - Base URL: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
  - Distinct request shape: `contents` array with `parts`
  - Auth: API key as query parameter from `GOOGLE_API_KEY`
  - Response parsing differs from OpenAI format
- [ ] `openrouter.go` -- OpenRouter API client (OpenAI-compatible):
  - Base URL: `https://openrouter.ai/api/v1/chat/completions`
  - Auth: Bearer token from `OPENROUTER_API_KEY`
  - Supports multiple model backends

### OpenAI-Compatible Base Client
- [ ] Extract shared `openaiCompatibleClient` struct for Groq, OpenAI, and OpenRouter:
  - Configurable base URL, API key header, model default
  - Shared request/response marshaling
  - Reduces code duplication across 3 providers

### Provider Registry
- [ ] Implement `Registry` struct that holds configured providers:
  - [ ] Priority ordering (configurable via environment or API)
  - [ ] Provider availability check (is API key set?)
  - [ ] Fallback logic: try primary provider, on failure try next in priority chain
  - [ ] Port multi-provider priority logic from `registry.py`

### HTTP Client Configuration
- [ ] Use Go `http.Client` with configurable timeouts per provider
- [ ] Implement retry logic with exponential backoff for transient errors (429, 500, 502, 503)
- [ ] Set appropriate `Content-Type` and auth headers per provider
- [ ] Parse rate limit headers for backoff decisions

### Token Usage Tracking
- [ ] Extract `prompt_tokens` and `completion_tokens` from provider responses
- [ ] Return `TokenUsage` struct from every `Generate()` call
- [ ] Feed into budget counter in `guardrails/budget.go`

## Acceptance Criteria

- All 5 providers (Groq, OpenAI, Anthropic, Google, OpenRouter) successfully make API calls and return parsed responses
- Fallback works: if primary provider returns error, secondary provider is tried
- Token usage is accurately reported for all providers
- Provider with missing API key is skipped in the priority chain
- Error responses from providers are correctly parsed and returned as Go errors

## Implementation Notes

- Groq, OpenAI, and OpenRouter share the same OpenAI-compatible HTTP contract. Use a shared base client struct.
- Anthropic has a distinct request shape: system prompt is a top-level field, not a message. Response uses `content[0].text` instead of `choices[0].message.content`.
- Google Gemini has a completely different request/response shape. Needs its own marshaling logic.
- Keep provider implementations stateless. Each `Generate()` call is independent.
- Use `context.Context` for cancellation and timeout propagation through HTTP calls.

## Files to Create

```
services/api/llm/
  client.go          -- LLMClient interface, Options, TokenUsage
  registry.go        -- Provider registry with priority chain and fallback
  openai_compat.go   -- Shared base client for OpenAI-compatible APIs
  groq.go            -- Groq provider
  openai.go          -- OpenAI provider
  anthropic.go       -- Anthropic provider
  google.go          -- Google Gemini provider
  openrouter.go      -- OpenRouter provider
```
