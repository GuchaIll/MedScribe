# Issue #39 -- HNSW Indexing, Embedding Pipeline, and RAG Benchmark

**Title:** feat(rag): implement HNSW indexing and embedding pipeline

**Phase:** 9 (RAG Grounding Benchmark) -- Steps 34-36

**Resume bullets served:** V2#3 (pgvector source-grounded RAG, 98% citation accuracy)

**Depends on:** Phase 8 (Evaluation Framework, Issue #38)

---

## Overview

Optimize the RAG pipeline with HNSW indexing for fast vector search, implement Go-native embedding dispatch (eliminating a Python sidecar), and benchmark citation accuracy to achieve 98% on the golden evaluation dataset.

## Goals

- Reduce embedding search latency from approximately 50ms to approximately 5ms via HNSW index
- Implement Go-native embedding generation (minimize Python surface area)
- Achieve 98% or higher citation accuracy on golden evaluation dataset
- Establish grounding threshold tuning methodology

## Scope

- Database: PostgreSQL + pgvector HNSW index
- Go orchestrator: embedding dispatch and evidence retrieval
- Evaluation: citation accuracy benchmark

## Tasks

### HNSW Index (Step 34)
- [ ] Create HNSW index on embedding column via SQL migration:
  ```sql
  CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
  ```
  - [ ] Use Alembic migration (if maintaining Python migration tooling) or raw SQL in Go migration tool
  - [ ] Index parameters: `m=16` (connections per layer), `ef_construction=64` (build-time search width)
  - [ ] Set `ef_search` at query time for accuracy/speed tradeoff (default: 40)
- [ ] Benchmark index performance:
  - [ ] Measure query latency before index (sequential scan) vs after (HNSW)
  - [ ] Target: approximately 5ms for ANN query vs approximately 50ms baseline
  - [ ] Measure recall at different `ef_search` values

### Go Embedding Dispatch (Step 35)
- [ ] **Recommended: Option B** -- Load ONNX-exported `all-MiniLM-L6-v2` model directly in Go:
  - [ ] Export `all-MiniLM-L6-v2` from HuggingFace to ONNX format (one-time step)
  - [ ] Use `onnxruntime-go` crate to load and run inference
  - [ ] Implement `EmbeddingService` interface:
    ```
    Embed(ctx context.Context, texts []string) ([][]float32, error)
    ```
  - [ ] Tokenization: port or use Go tokenizer library compatible with MiniLM vocabulary
  - [ ] Batch inference support for multiple texts
  - [ ] No Python dependency for embeddings
- [ ] **Alternative: Option A** -- gRPC call to Python `sentence-transformers` sidecar:
  - [ ] `services/embedding/` Python service
  - [ ] gRPC endpoint: `Embed(texts) -> embeddings`
  - [ ] Uses exact same model (`all-MiniLM-L6-v2`)
  - [ ] Adds one more Python service but guaranteed model compatibility
- [ ] Integrate embedding dispatch into `retrieve_evidence` node:
  - [ ] Generate embedding for query text
  - [ ] Execute pgvector ANN query via `pgx`:
    ```sql
    SELECT chunk_id, text, embedding <=> $1 AS distance
    FROM embeddings
    WHERE distance < $2
    ORDER BY distance
    LIMIT $3
    ```
  - [ ] Map results to `[]EvidenceItem`

### Citation Accuracy Benchmark (Step 36)
- [ ] Extend eval harness from Issue #38 with citation-specific scoring:
  - [ ] For each field in `evidence_map`:
    - Retrieve cited source chunk
    - Verify chunk text contains supporting evidence for the fact
    - Score: correct citation (1) or incorrect citation (0)
  - [ ] Calculate aggregate citation accuracy: (correct / total)
  - [ ] Target: >= 98% on golden evaluation dataset
- [ ] Grounding threshold sweep:
  - [ ] Current `grounding_threshold` value: 0.65 (from `config.py`)
  - [ ] Test range: 0.50 to 0.90 in 0.05 increments
  - [ ] For each threshold:
    - Run pipeline on evaluation dataset
    - Measure citation accuracy
    - Measure evidence recall (facts with supporting evidence)
  - [ ] Select optimal threshold balancing accuracy and recall
  - [ ] Output: threshold vs accuracy/recall curve (markdown table or CSV)
- [ ] Regression gate:
  - [ ] CI blocks PRs that reduce citation accuracy below 98%
  - [ ] Report threshold sensitivity in eval output

## Acceptance Criteria

- HNSW index reduces ANN search latency from approximately 50ms to approximately 5ms
- Go ONNX embedding produces vectors compatible with existing pgvector embeddings (cosine similarity matches Python sentence-transformers output within 0.01 tolerance)
- Citation accuracy >= 98% on golden evaluation dataset
- Grounding threshold sweep produces clear accuracy/recall tradeoff analysis
- CI gate blocks regressions below 98% citation accuracy

## Implementation Notes

- **Option B (Go ONNX) is recommended** to minimize Python surface area. The tradeoff is a one-time model export step and ensuring tokenizer compatibility.
- `onnxruntime-go` supports Linux and macOS. Ensure CI/CD builds include ONNX Runtime shared library.
- HNSW index parameters (`m=16`, `ef_construction=64`) are good defaults for datasets up to 1M vectors. Adjust for production scale.
- The `<=>` operator in pgvector computes cosine distance. Use `<->` for L2 distance. Current pipeline uses cosine.
- Embedding dimension for `all-MiniLM-L6-v2` is 384.
- Grounding threshold is the minimum similarity score for an evidence chunk to be considered supporting. Lower threshold = more evidence retrieved, higher recall but potentially lower precision.

## Files to Create

```
services/orchestrator/embedding/
  onnx.go           -- Go ONNX runtime embedding service (Option B)
  tokenizer.go      -- MiniLM tokenizer for Go

models/
  all-MiniLM-L6-v2.onnx  -- Exported ONNX model file

eval/scoring/
  citation.go       -- Citation accuracy scorer (extend from Issue #38)
  threshold.go      -- Grounding threshold sweep tool

migrations/
  xxx_add_hnsw_index.sql  -- HNSW index creation migration
```

## Dependencies

- `github.com/yalue/onnxruntime_go` -- ONNX Runtime Go bindings (Option B)
- pgvector HNSW index support (pgvector >= 0.5.0)
