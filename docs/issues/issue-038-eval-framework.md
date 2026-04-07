# Issue #38 -- Evaluation Harness for Pipeline Accuracy

**Title:** feat(eval): implement evaluation harness for pipeline accuracy

**Phase:** 8 (Evaluation Framework) -- Steps 31-33

**Resume bullets served:** V1#3 (hallucination rate, transcript accuracy, latency)

---

## Overview

Build an evaluation framework to measure pipeline quality across multiple dimensions: hallucination rate, transcript accuracy (WER), per-node latency, and citation accuracy. The framework supports multi-model comparison and CI gating on quality regressions.

## Goals

- Establish repeatable quality benchmarks for the clinical pipeline
- Detect regressions in pipeline accuracy before merging PRs
- Compare output quality across different LLM providers and models
- Quantify hallucination rate, transcript WER, and citation accuracy

## Scope

- Directory: `eval/`
- Depends on: Go orchestrator gRPC endpoint (Phase 1), Prometheus metrics (Phase 7)

## Tasks

### Golden Evaluation Dataset (Step 31)
- [ ] Create `eval/datasets/` directory with 20-50 annotated clinical encounters:
  - [ ] Each entry contains:
    - Input transcript segments (raw audio transcriptions)
    - Input patient context (prior history)
    - Expected candidate facts (golden list of clinical entities)
    - Expected structured record fields
    - Reference clinical note
    - Reference transcript text (for WER calculation)
  - [ ] Dataset format: JSON files, one per encounter
  - [ ] Annotation schema definition in `eval/datasets/schema.json`
- [ ] Reuse structure from existing test fixtures in `tests/`
- [ ] Include diverse clinical scenarios:
  - [ ] New patient intake
  - [ ] Follow-up visit with prior history
  - [ ] Multi-problem encounter
  - [ ] Edge cases: conflicting information, incomplete data

### Eval Harness (Step 32)
- [ ] Implement evaluation runner (Go CLI tool or Python script):
  - [ ] For each dataset entry:
    1. Submit to Go orchestrator via `RunPipeline` gRPC endpoint
    2. Collect pipeline output (structured record, clinical note, evidence map)
    3. Score against golden annotations
  - [ ] Configurable orchestrator endpoint and timeout

- [ ] Implement scoring metrics:
  - [ ] **Hallucination rate**: Compare generated entities against golden list
    - Port `MedicalFactsGuardrail` regex logic from `medical_facts.py`
    - Calculate: (entities NOT in golden list) / (total generated entities)
    - Target: < 5%
  - [ ] **Transcript WER** (Word Error Rate): Compare Whisper output against reference transcript
    - Standard WER calculation: (substitutions + insertions + deletions) / reference length
    - Per-encounter and aggregate WER
  - [ ] **Per-node latency**: Read from Prometheus metrics or pipeline progress Redis data
    - p50, p95, p99 per node
    - Total pipeline latency
  - [ ] **Citation accuracy**: Verify `evidence_map` links to correct source chunks
    - For each fact in evidence_map, check if cited source chunk contains supporting text
    - Calculate: (correct citations) / (total citations)
    - See Issue #39 for extended benchmark

- [ ] Output format:
  - [ ] Per-encounter results (JSON)
  - [ ] Aggregate summary (markdown table)
  - [ ] Pass/fail status based on configurable thresholds

### Multi-Model Comparison (Step 33)
- [ ] Iterate over provider/model pairs:
  - [ ] Configure list of models to evaluate (e.g., GPT-4, Claude, Llama-3.3-70b)
  - [ ] Run full dataset against each model
  - [ ] Collect metrics per model
- [ ] Output: side-by-side markdown comparison table:
  - [ ] Columns: model, hallucination rate, WER, avg latency, citation accuracy, estimated cost
  - [ ] Highlight best/worst per metric

### CI Integration
- [ ] GitHub Actions workflow for evaluation:
  - [ ] Trigger on PR (optional, gated by label)
  - [ ] Run eval harness against a subset of the dataset (fast mode)
  - [ ] Fail PR if any metric regresses beyond threshold:
    - Hallucination rate > 5%
    - WER increase > 2% from baseline
    - Citation accuracy < 95%
  - [ ] Post results as PR comment

## Acceptance Criteria

- Eval harness produces comparison table for at least 2 models
- Hallucination rate is measured and reported for each run
- CI workflow blocks PRs that regress on quality metrics
- Results are reproducible: same dataset + same model = same scores (within LLM variance)
- Evaluation completes within reasonable time (< 30 minutes for full dataset)

## Implementation Notes

- Start with a Go CLI tool (`eval/cmd/eval/main.go`) that calls the orchestrator gRPC endpoint. Python script is acceptable if faster to implement.
- Golden dataset quality is critical: invest time in accurate annotations
- LLM outputs are non-deterministic. Use temperature=0 for evaluation runs and report variance across multiple runs if needed.
- WER calculation can use an existing library (Go: custom implementation is simple; Python: `jiwer`)
- Hallucination detection reuses the same regex patterns from `medical_facts.py` guardrail

## Files to Create

```
eval/
  cmd/
    eval/
      main.go        -- CLI entry point
  datasets/
    schema.json      -- Dataset annotation schema
    encounter_001.json
    encounter_002.json
    ...
  scoring/
    hallucination.go -- Hallucination rate calculator
    wer.go           -- Word error rate calculator
    citation.go      -- Citation accuracy checker
    latency.go       -- Latency metric collector
  report/
    markdown.go      -- Markdown table report generator
    comparison.go    -- Multi-model comparison output

.github/workflows/
  eval.yml           -- CI workflow for evaluation
```
