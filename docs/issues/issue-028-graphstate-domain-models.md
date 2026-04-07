# Issue #28 -- Port GraphState and Domain Models to Go

**Title:** refactor(orchestrator): port GraphState and domain models to Go structs

**Phase:** 1 (Go API Gateway + Orchestrator Core) -- Steps 3 and 5

**Resume bullets served:** V2#1 (high-throughput pipeline)

---

## Overview

Translate all Python TypedDict types from `state.py` and the `AgentContext` dataclass from `config.py` into Go structs and interfaces. These are the foundational types used by every pipeline node and the DAG execution engine.

## Goals

- Establish Go type definitions for all pipeline state and domain objects
- Define Go interfaces for dependency injection into node functions
- Ensure JSON serialization compatibility for checkpoint persistence

## Scope

- Directory: `services/orchestrator/`
- Files: `state.go`, `context.go`
- Replaces:
  - `state.py` (GraphState and related TypedDicts)
  - `config.py` (AgentContext dataclass)

## Tasks

### Port GraphState and Related Types (Step 3)

- [ ] Port `GraphState` TypedDict to Go struct with `json:"..."` tags:
  - Session identifiers: `session_id`, `patient_id`, `doctor_id`
  - Raw input: `conversation_log`, `new_segments`, `documents`
  - Intermediate state: `session_summary`, `patient_record_fields`, `chunks`, `candidate_facts`, `evidence_map`
  - Validated output: `structured_record`, `validation_report`, `conflict_report`, `clinical_suggestions`, `diagnostic_reasoning`
  - Final output: `clinical_note`
  - Control flow: `flags`, `is_new_patient`, `message`, `inputs`, `controls`

- [ ] Port `TranscriptSegment` TypedDict:
  - `speaker`, `text`, `start_time`, `end_time`, `confidence`

- [ ] Port `ConversationTurn` TypedDict:
  - `role`, `content`, `timestamp`

- [ ] Port `DocumentArtifact` TypedDict:
  - `document_id`, `filename`, `document_type`, `pages`, `extracted_text`, `fields`, `confidence_scores`

- [ ] Port `ChunkArtifact` TypedDict:
  - `chunk_id`, `text`, `source_type`, `metadata`

- [ ] Port `CandidateFact` TypedDict:
  - `fact_id`, `field_name`, `value`, `confidence`, `source_chunk_id`, `reasoning`

- [ ] Port `EvidenceItem` TypedDict:
  - `chunk_id`, `text`, `similarity_score`, `source_type`

- [ ] Port `ValidationReport` TypedDict:
  - `is_valid`, `schema_errors`, `missing_fields`, `confidence_flags`, `conflicts`, `needs_review`

- [ ] Port `ConflictReport` TypedDict:
  - `conflicts`, `resolution_status`, `unresolved_count`

- [ ] Port `Controls` TypedDict:
  - `repair_attempts`, `max_repair_attempts`, `llm_call_count`, `max_llm_calls`, `trace_log`, `grounding_threshold`

### Port AgentContext as Go Interfaces (Step 5)

- [ ] Define `Context` struct for dependency injection into node functions:
  ```
  type Context struct {
      LLM          LLMClient
      Embeddings   EmbeddingService
      Patients     PatientRepository
      Records      RecordRepository
      Sessions     SessionRepository
      DB           *pgxpool.Pool
      MaxLLMCalls  int
      GroundingThr float64
  }
  ```

- [ ] Define `LLMClient` interface:
  - `Generate(ctx context.Context, prompt, systemPrompt string, opts Options) (string, TokenUsage, error)`

- [ ] Define `EmbeddingService` interface:
  - `Embed(ctx context.Context, texts []string) ([][]float32, error)`

- [ ] Define `PatientRepository` interface:
  - `GetByID(ctx context.Context, id string) (*Patient, error)`
  - `Search(ctx context.Context, query string) ([]*Patient, error)`
  - `Update(ctx context.Context, patient *Patient) error`

- [ ] Define `RecordRepository` interface:
  - `GetBySessionID(ctx context.Context, sessionID string) (*MedicalRecord, error)`
  - `Save(ctx context.Context, record *MedicalRecord) error`
  - `GetByPatientID(ctx context.Context, patientID string) ([]*MedicalRecord, error)`

- [ ] Define `SessionRepository` interface:
  - `Create(ctx context.Context, session *Session) error`
  - `GetByID(ctx context.Context, id string) (*Session, error)`
  - `Update(ctx context.Context, session *Session) error`

### JSON Serialization

- [ ] Add `json:"..."` struct tags to all types for checkpoint persistence
- [ ] Validate round-trip serialization: marshal GraphState to JSON, unmarshal, compare
- [ ] Ensure compatibility with existing Python-generated checkpoint JSON (if migration is needed)

## Acceptance Criteria

- All TypedDict types from `state.py` have corresponding Go structs
- Go interfaces match the dependency injection pattern used in Python `AgentContext`
- GraphState can be serialized to JSON and deserialized without data loss
- All struct fields have appropriate `json` tags matching the Python field names
- Node functions can be written with signature `func(state *GraphState, ctx *Context) (*GraphState, error)`

## Implementation Notes

- Use pointer types for optional fields (e.g., `*ValidationReport` for nullable fields)
- Use `[]T` (not `*[]T`) for list fields -- Go JSON marshaling handles nil slices as `null`
- `Controls.trace_log` is a `[]TraceEntry` where each entry has: node name, action, timestamp, detail
- The `evidence_map` field is `map[string][]EvidenceItem` -- maps fact_id to source chunks
- The `flags` field is `map[string]bool` -- keys include `awaiting_human_review`, `processing_error`
- Keep type names consistent with Python originals for cross-reference during porting

## Files to Create

```
services/orchestrator/
  state.go     -- GraphState, TranscriptSegment, ConversationTurn, DocumentArtifact,
                  ChunkArtifact, CandidateFact, EvidenceItem, ValidationReport,
                  ConflictReport, Controls, TraceEntry
  context.go   -- Context struct, LLMClient, EmbeddingService, PatientRepository,
                  RecordRepository, SessionRepository interfaces
```
