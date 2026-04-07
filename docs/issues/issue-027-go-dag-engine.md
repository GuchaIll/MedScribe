# Issue #27 -- Go DAG Execution Engine

**Title:** feat(orchestrator): implement Go-based DAG execution engine

**Phase:** 1 (Go API Gateway + Orchestrator Core) -- Step 2

**Resume bullets served:** V2#1 (high-throughput pipeline), V1#1 (decoupling ingestion from serving)

---

## Overview

Replace LangGraph with a custom Go-based DAG engine to execute the 18-node clinical pipeline with checkpointing, conditional routing, and progress tracking. LangGraph is Python-only with no Go/Rust bindings, and the current pipeline is a linear chain with 2 branch points, making a custom engine both feasible and preferable.

## Goals

- Deterministic pipeline execution with error handling and budget tracking
- Support checkpoint and resume via PostgreSQL persistence
- Enable real-time progress updates via Redis pub/sub
- Expose gRPC interface for remote invocation from Kafka consumers

## Scope

- Directory: `services/orchestrator/`
- Replaces:
  - `graph.py` (LangGraph StateGraph definition)
  - `workflow_engine.py` (async execution wrapper)

## Tasks

### Core Engine
- [ ] Implement node registry: `map[string]NodeFunc` where `NodeFunc = func(*GraphState, *Context) (*GraphState, error)`
  - Mirrors `graph.py` nodes dict
- [ ] Implement edge system:
  - [ ] Linear edges: `map[string]string` for direct node-to-node transitions
  - [ ] Conditional edges: `map[string]func(*GraphState) string` for branch decisions
  - Mirrors `graph.add_edge()` and `graph.add_conditional_edges()`
- [ ] Build execution loop:
  - [ ] Iterate from entry point, call node function, follow edge, repeat until END
  - [ ] Goroutine-based async execution with `context.Context` cancellation
  - [ ] Budget tracking: count LLM calls per pipeline run, enforce max from `Controls.max_llm_calls`
  - [ ] Error handling: per-node error capture, propagation to caller
  - [ ] Stream progress updates to Redis after each node completes

### Conditional Routing
- [ ] Port `_route_after_validate()` from `graph.py` lines 60-77:
  - Schema errors present AND `repair_attempts < 3` --> `repair`
  - Conflicts present --> `conflict_resolution`
  - `needs_review` true --> `human_review_gate`
  - Default (valid) --> `generate_note`
- [ ] Port `_route_after_conflict()` from `graph.py`:
  - Unresolved conflicts --> `human_review_gate`
  - Resolved --> `generate_note`

### Checkpoint Persistence
- [ ] Serialize full `GraphState` as JSON to PostgreSQL `workflow_checkpoints` table after each node
- [ ] Key checkpoints by `session_id` + `node_name` + `timestamp`
- [ ] Implement resume: load last checkpoint for a given `session_id`, deserialize, replay from interrupted node
- [ ] Handle the `human_review_gate` interrupt: checkpoint state, mark as `needs_review`, await external resume signal

### Progress Tracking
- [ ] Write progress to Redis hash `pipeline:{session_id}` after each node completes
- [ ] Include: current node name, node index, total nodes, start time, elapsed time, status
- [ ] Publish updates via Redis pub/sub for real-time WebSocket delivery
- [ ] Replaces the current in-memory `pipeline_progress_store` from `pipeline_progress.py`

### gRPC Interface
- [ ] Define protobuf service in `proto/orchestrator.proto`:
  - [ ] `RunPipeline(RunPipelineRequest) returns (RunPipelineResponse)` -- trigger full pipeline
  - [ ] `GetProgress(GetProgressRequest) returns (GetProgressResponse)` -- poll progress
  - [ ] `ResumeFromCheckpoint(ResumeRequest) returns (RunPipelineResponse)` -- resume interrupted pipeline
- [ ] Implement gRPC server using `google.golang.org/grpc`

## Acceptance Criteria

- Full 18-node pipeline executes correctly end-to-end
- Resume works after mid-pipeline interruption (kill process, restart, resume from checkpoint)
- Conditional routing at `validate_and_score` and `conflict_resolution` matches Python reference behavior
- Output matches Python reference pipeline on existing test fixtures
- Progress updates appear in Redis in real time during execution

## Implementation Notes

- The pipeline is a **linear chain with 2 branch points**, not an arbitrary DAG. A simple `for` loop with a `switch` at the branch points covers it. Avoid overengineering.
- Serialize `GraphState` as JSON for persistence. Go `encoding/json` with struct tags handles this.
- Use `context.Context` for cancellation and timeout propagation through the pipeline
- The repair loop (validate -> repair -> validate) has a max iteration count of 3, enforced by `Controls.repair_attempts`

## Key Risk

The LangGraph replacement is the biggest lift. The current 18-node pipeline with conditional routing, repair loops, and checkpoint/resume is approximately 800 lines of Python orchestration. The Go equivalent needs:
- Node execution with error handling and budget tracking
- Conditional edge evaluation after `validate_and_score` and `conflict_resolution`
- Checkpoint serialization to PostgreSQL (JSON marshal of full GraphState)
- Resume from checkpoint (deserialize, replay from interrupted node)

This is feasible because the graph is a linear pipeline with 2 branch points.

## Files to Create

```
services/orchestrator/
  main.go
  engine.go          -- DAG execution loop, node registry, edge table
  state.go           -- GraphState and related structs (see Issue #28)
  context.go         -- Context with injected dependencies (see Issue #28)
  progress/
    redis.go         -- Redis hash + pub/sub progress updates
  Dockerfile
  go.mod
  go.sum

proto/
  orchestrator.proto -- gRPC service definition
```

## Dependencies

- `github.com/jackc/pgx/v5` -- PostgreSQL checkpoint persistence
- `github.com/redis/go-redis/v9` -- Redis progress tracking
- `google.golang.org/grpc` -- gRPC server
- `google.golang.org/protobuf` -- protobuf code generation
