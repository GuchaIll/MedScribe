# Issue #35 -- Redis Integration, Distributed State, and OCC

**Title:** feat(state): add Redis for caching, progress tracking, and OCC

**Phase:** 6 (Distributed State) -- Steps 23-27

**Resume bullets served:** V2#4 (PostgreSQL + Redis, OCC)

---

## Overview

Introduce Redis to support distributed state management, real-time pipeline progress tracking, LLM response caching, and optimistic concurrency control (OCC) across services. Redis replaces the current in-memory `pipeline_progress_store` from `pipeline_progress.py`.

## Goals

- Enable real-time pipeline progress tracking across distributed services
- Reduce redundant LLM calls via response caching
- Ensure safe concurrent updates using optimistic concurrency control
- Support distributed locks for critical sections

## Scope

- Applies to:
  - Go API gateway (`services/api/`)
  - Go orchestrator (`services/orchestrator/`)
- Infrastructure: `docker-compose.yml`

## Tasks

### Redis Infrastructure (Step 23)
- [ ] Add Redis to `docker-compose.yml`:
  - [ ] Image: `redis:7-alpine`
  - [ ] Port: 6379
  - [ ] Persistent volume for data durability
  - [ ] Health check configuration
- [ ] Integrate `go-redis/redis/v9` client in Go services:
  - [ ] Connection pool configuration
  - [ ] Retry and reconnection logic
  - [ ] Sentinel/Cluster support for production (configurable)

### Pipeline Progress in Redis (Step 24)
- [ ] Go orchestrator writes progress to Redis hash `pipeline:{session_id}` after each node:
  - [ ] Fields: `current_node`, `node_index`, `total_nodes`, `status`, `start_time`, `elapsed_ms`, `last_updated`
  - [ ] Status values: `running`, `completed`, `failed`, `paused` (human review gate)
- [ ] Publish progress updates via Redis pub/sub channel `pipeline:progress:{session_id}`:
  - [ ] Enables real-time WebSocket delivery to frontend
- [ ] Go API gateway reads Redis hash for polling endpoint `GET /api/session/{id}/pipeline/status`
- [ ] TTL on progress keys: auto-expire after 24 hours
- [ ] Replaces current in-memory `pipeline_progress_store` from `pipeline_progress.py`

### Checkpoint Persistence in PostgreSQL (Step 25)
- [ ] Go orchestrator serializes full `GraphState` as JSON to `workflow_checkpoints` table after each node:
  - [ ] Columns: `id`, `session_id`, `node_name`, `state_json`, `created_at`
  - [ ] Index on `(session_id, created_at DESC)` for efficient latest-checkpoint lookup
- [ ] Resume implementation:
  - [ ] Load last checkpoint for a `session_id`
  - [ ] Deserialize JSON back to `GraphState`
  - [ ] Replay pipeline from the interrupted node
- [ ] Checkpoint cleanup: retain last N checkpoints per session, prune older entries

### Optimistic Concurrency Control (Step 26)
- [ ] `medical_records` table already has a `version` column
- [ ] Add `version` column to `patients` and `sessions` tables via SQL migration:
  - [ ] Default value: 1
  - [ ] Increment on every update
- [ ] Go repository `Update()` methods include `WHERE version = $expected`:
  - [ ] Return `ErrStaleData` error on zero rows affected
  - [ ] Caller must re-read and retry on stale data
- [ ] Apply OCC to all write paths:
  - [ ] `PatientRepository.Update()`
  - [ ] `RecordRepository.Save()`
  - [ ] `SessionRepository.Update()`

### Redis LLM Response Cache (Step 27)
- [ ] Cache key: `llm:cache:{sha256(prompt + provider + model)}`
- [ ] Cache value: JSON serialized response (text + token usage)
- [ ] TTL: 5 minutes (configurable)
- [ ] Check cache before calling provider in LLM dispatch:
  - [ ] Cache hit: return cached response, skip API call
  - [ ] Cache miss: call provider, store response in cache
- [ ] Cache bypass option for requests requiring fresh responses
- [ ] Metrics: cache hit rate, cache miss rate

### Distributed Locks
- [ ] Implement Redis-based distributed lock for critical sections:
  - [ ] Pipeline execution lock per session (prevent duplicate runs)
  - [ ] Lock with configurable TTL and retry
  - [ ] Use `SET NX EX` pattern for atomic lock acquisition

## Acceptance Criteria

- Pipeline progress is visible in real time via Redis during pipeline execution
- Kill orchestrator mid-pipeline, restart, pipeline resumes from PostgreSQL checkpoint at correct node
- Two concurrent record updates: one succeeds, the other gets `ErrStaleData`
- Cached LLM responses reduce duplicate API calls (verified by cache hit counter)
- Distributed lock prevents duplicate pipeline execution for the same session
- Redis connection handles reconnection gracefully after transient failures

## Implementation Notes

- Use Redis hashes (HSET/HGETALL) for structured progress data -- more efficient than serialized JSON strings
- Use short TTLs for LLM cache to avoid stale responses (medical context changes between requests)
- Handle cache misses gracefully -- cache is an optimization, not a requirement
- OCC version column should use `BIGINT` type for the version counter
- PostgreSQL checkpoint JSON can be large (full GraphState). Consider JSONB column type for indexing capability.
- The `workflow_checkpoints` table may already exist from the LangGraph SQLite migration; verify schema compatibility

## Files to Create/Modify

```
services/orchestrator/progress/
  redis.go          -- Redis hash + pub/sub progress tracking

services/api/store/
  (modify existing repos to add OCC WHERE version = $expected)

services/api/llm/
  cache.go          -- Redis LLM response cache

docker-compose.yml  -- Add redis service
```

## Dependencies

- `github.com/redis/go-redis/v9` -- Redis client for Go
