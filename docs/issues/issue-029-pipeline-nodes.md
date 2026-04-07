# Issue #29 -- Port 18 Pipeline Nodes to Go

**Title:** feat(orchestrator): port 18 pipeline nodes from Python to Go

**Phase:** 1 (Go API Gateway + Orchestrator Core) -- Step 4

**Resume bullets served:** V2#1 (high-throughput pipeline)

---

## Overview

Convert all 18 pipeline node functions from Python to Go, preserving existing behavior. Each node becomes a Go function with the standard signature `func(state *GraphState, ctx *Context) (*GraphState, error)`. Nodes are grouped by complexity: pure logic, LLM-calling, DB-reading, RAG, rule-based, and gate.

## Goals

- Preserve existing pipeline behavior exactly
- Ensure modular and testable node implementations
- Isolate side effects (DB, LLM, external API calls) behind Context interfaces

## Scope

- Directory: `services/orchestrator/nodes/`
- Also: `services/orchestrator/guardrails/`, `services/orchestrator/validation/`, `services/orchestrator/ocr/`
- Covers all 18 pipeline nodes from `server/app/agents/nodes/`

## Tasks

### Pure Logic Nodes (no LLM, no DB)
- [ ] `greeting.go` -- Seeds initial state, sets physician welcome message. Direct port of inline logic from `graph.py`.
- [ ] `ingest.go` -- Loads transcript segments and OCR artifacts into `GraphState.chunks`. Merges `new_segments` and `documents` into unified chunk list.
- [ ] `clean_transcription.go` -- Removes disfluencies (um, uh, repetitions), expands medical abbreviations. Pure text processing.
- [ ] `normalize_transcript.go` -- Standardizes medical terminology. Regex-based normalization rules.
- [ ] `segment_and_chunk.go` -- Splits transcript into topical clinical chunks. Text segmentation logic.
- [ ] `package_outputs.go` -- Assembles final response payload from processed state fields.

### LLM-Calling Nodes
- [ ] `extract_candidates.go` -- NLP entity recognition via LLM. Makes HTTP POST to cloud LLM API via `Context.LLM.Generate()`. Prompt template ports as Go `text/template` or string formatting. Parses LLM JSON response into `[]CandidateFact`.
- [ ] `diagnostic_reasoning.go` -- LLM differential diagnosis over extracted candidates. Sends candidate facts to LLM, receives structured diagnostic analysis.
- [ ] `repair.go` -- LLM schema repair. Takes `validation_report.schema_errors`, asks LLM to fix structured record fields. Loops back to validate (max 3 iterations via `Controls.repair_attempts`).
- [ ] `generate_note.go` -- LLM SOAP note generation. Takes structured record and clinical context, produces formatted clinical note.

### DB-Reading Nodes
- [ ] `load_patient_context.go` -- Loads prior patient facts from PostgreSQL via `Context.Patients.GetByID()` into `patient_record_fields`. Queries existing patient history for cross-visit context.
- [ ] `persist_results.go` -- Writes final `structured_record`, embeddings, and audit trace (`Controls.trace_log`) to PostgreSQL via `Context.Records.Save()`. This is the terminal data node.

### RAG Node
- [ ] `retrieve_evidence.go` -- pgvector ANN search via `Context.DB` using `embedding <-> $1` syntax. Embedding generation calls `Context.Embeddings.Embed()` (Go ONNX runtime or Python sidecar). Returns `evidence_map` mapping fact_id to source chunks with similarity scores.

### Rule-Based Nodes
- [ ] `validate_and_score.go` -- Per-field validation using contracts from `validation_contracts.py`. Checks:
  - Schema errors (required fields, type constraints)
  - Confidence thresholds per field (`min_confidence` from CONTRACT dict)
  - Cross-visit contradiction detection against stored patient history
  - Sets `validation_report.needs_review` flag
- [ ] `conflict_resolution.go` -- Resolves discrepancies against stored patient history. Produces `ConflictReport` with resolution status.
- [ ] `clinical_suggestions.go` -- Rule-based drug interaction lookup and allergy checking. Pure logic, no ML. Port clinical rules from `clinical_suggestions.py`.
- [ ] `fill_structured_record.go` -- Maps `candidate_facts` to typed `StructuredRecord` schema fields based on `field_name` matching and confidence ranking.

### Gate Node
- [ ] `human_review_gate.go` -- Checkpoint to PostgreSQL, mark state as `needs_review`, set `flags["awaiting_human_review"] = true`. Await external resume signal via `ResumeFromCheckpoint` gRPC call.

### Supporting Modules
- [ ] Port guardrails from `guardrails/*.py`:
  - [ ] `guardrails/budget.go` -- LLM call budget counter, enforces `Controls.max_llm_calls`
  - [ ] `guardrails/medical_facts.go` -- Medical fact regex checker for hallucination detection
- [ ] Port validation contracts from `validation_contracts.py`:
  - [ ] `validation/contracts.go` -- Per-field confidence thresholds, schema rules, required field definitions
- [ ] Port OCR pipeline from `ocr/` (10 stages):
  - [ ] `ocr/pipeline.go` -- Orchestrates 10-stage OCR processing
  - [ ] Image preprocessing stages call Tesseract CLI via `exec.Command`
  - [ ] LLM-based field extraction calls cloud APIs via `Context.LLM`
  - [ ] No Python dependency for OCR

## Acceptance Criteria

- Each node output matches the Python implementation given the same input state
- LLM-calling nodes successfully make HTTP calls to cloud APIs and parse responses
- Database and RAG interactions work correctly against the existing PostgreSQL schema
- Repair loop correctly iterates up to 3 times between `validate_and_score` and `repair`
- All guardrails and validation contracts produce identical results to Python versions
- OCR pipeline processes documents without Python dependency

## Implementation Notes

- Standard function signature for all nodes: `func(state *GraphState, ctx *Context) (*GraphState, error)`
- Keep nodes as pure as possible. All side effects (DB reads, LLM calls, embedding queries) go through `Context` interfaces, enabling easy testing with mocks.
- LLM prompt templates: port as Go `text/template` files or embedded strings. Ensure prompt text is identical to Python originals.
- For the RAG node, pgvector queries use `pgx` with the `<->` (L2 distance) or `<=>` (cosine distance) operator
- The `human_review_gate` is currently non-interactive (`enable_interrupts=False`), but the infrastructure must support future interactive use

## Files to Create

```
services/orchestrator/nodes/
  greeting.go
  load_patient_context.go
  ingest.go
  clean_transcription.go
  normalize_transcript.go
  segment_and_chunk.go
  extract_candidates.go
  diagnostic_reasoning.go
  retrieve_evidence.go
  fill_structured_record.go
  clinical_suggestions.go
  validate_and_score.go
  repair.go
  conflict_resolution.go
  human_review_gate.go
  generate_note.go
  package_outputs.go
  persist_results.go

services/orchestrator/guardrails/
  budget.go
  medical_facts.go

services/orchestrator/validation/
  contracts.go

services/orchestrator/ocr/
  pipeline.go
  stages.go
```
