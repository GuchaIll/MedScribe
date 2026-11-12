# 104 — Retrieval eval set + Recall@5/MRR baseline for current hybrid retriever

**Issue:** #104
**Parent issue:** none (related: #98 reuses the dataset and scorer, #81 public claims, #49 harness)
**Sub-issues:** none
**Branch:** `feat/104-retrieval-eval-baseline`
**Source docs:** `docs/benchmarks/README.md` (audit table, "85% target, not measured" row); #98 "Harness" section

## Goal

Measure the retriever on `main` today (`HybridRetrievalService.search_chunks_for_patient`) on a
100-query labeled synthetic eval set, and commit the numbers (Recall@1/5/10, MRR, bootstrap
95% CIs, per-stratum, leakage) as an evidence pack in `docs/benchmarks/retrieval-accuracy/`.

## Scope

In scope:
- Synthetic corpus (10 fake patients, 4 documents each) and 100 labeled queries.
- Loader + validation, gold resolution, scorer, runner CLI, evidence pack, benchmark README row.
- Leg diagnostics: dense-only and sparse-only metrics from the same retriever's two legs,
  so a reader can tell which leg the hybrid number comes from.

Out of scope:
- Reranker, chunking A/B, `context_prefix` ablation, page-split tables (#98).
- Grounded-answer rate (#57).
- Changing retriever behavior. This ticket measures it as-is, including its weaknesses.

## Design

### What is measured, exactly

- Corpus documents go through the production functions unchanged:
  `segment.chunk_documents()` (500 chars, 50 overlap) -> `EmbeddingService.store_chunk_embeddings_batch()`
  (BioLord-2023-M, 768-d) -> `chunk_embeddings` in Postgres + pgvector, schema from `alembic upgrade head`
  (so the ivfflat and GIN indexes are the real ones).
- Each patient gets one session; all of a patient's documents attach to it.
- Query path: `HybridRetrievalService.search_chunks_for_patient(patient_id, query, top_k=k)`.
  Two calls per query: `k=5` (Recall@1, Recall@5) and `k=10` (Recall@10, MRR@10). Two calls
  because RRF over legs truncated at `2k` is not prefix-stable, so top-5 of a `k=10` call is
  not what a `k=5` caller sees.
- Finding recorded during scoping: no code under `server/app/` writes `chunk_embeddings` today
  (only a unit test). The number describes the retriever given an ingested corpus, not the
  live pipeline end to end. The evidence README says so.

### Gold labels

Gold is anchored to source text, not `chunk_id` (chunk ids are random uuids today and change
with #98's chunker). A gold span is `{doc_id, quote}`. A retrieved chunk is a hit when its
whitespace/case-normalized text contains the normalized quote.

Resolution at load time (pure Python, no DB): run the corpus through `chunk_documents()` and
map each quote to the chunks containing it.
- 0 chunks: load error (quote straddles a chunk boundary or has a typo; rewrite it).
- 2+ chunks in the same document: allowed. The 50-char overlap legitimately repeats text.
- Quote present in another document of the same patient: load error (ambiguous label).

Because the runner seeds with random chunk ids, hit testing in the runner uses the same text
containment rule against returned `chunk_text`, which is equivalent to the resolved id set.

### Strata

`exact_term`, `paraphrase`, `numeric`, `medication`, `negative`. Negatives have `gold: []`.
They are excluded from recall/MRR and scored separately as `negative_nonempty_rate` (share of
negatives where the retriever returned at least one chunk). The retriever has no abstention,
so this is expected to be high; it is reported, not hidden.

### Metrics

- Recall@k (k in 1, 5, 10): share of positive queries with at least one gold hit in the top k.
- MRR@10: mean of 1/rank of the first gold hit in the `k=10` list, 0 if none.
- 95% CIs: percentile bootstrap, 2000 resamples, fixed seed 104.
- Leakage: count of returned chunks whose seeded patient differs from the query's patient. Must be 0.

### Data model proof

New models live in `server/evals/retrieval/dataset.py`. No existing model covers an eval row;
`ChunkArtifact` / `DocumentArtifact` are reused as-is for chunking, not duplicated.

`EvalQuery` (one line of `queries.jsonl`):

| Field | Consumer |
|---|---|
| `query_id` | per-query rows in `results.json`; duplicate check; failure listing |
| `patient_id` | `search_chunks_for_patient` scope; leakage check; gold doc must belong to this patient |
| `query` | retriever input |
| `stratum` | per-stratum breakdown; negative handling |
| `gold: list[GoldSpan]` | resolution check; hit test |

`GoldSpan`: `doc_id` (resolution + ambiguity check), `quote` (hit test).

`CorpusDocument`: `doc_id` (gold reference, becomes `DocumentArtifact.document_id`),
`patient_id` (seeding scope, leakage map), `text` (`DocumentArtifact.extracted_text`).
Dropped during implementation: `title` (nothing reads it) and `source_type` (`chunk_documents`
copies it into chunk metadata, which is never stored). The corpus is plain files,
`corpus/<patient_id>/<doc_id>.txt`, so ids come from the path and documents are reviewable as text.

`ResolvedEvalSet` (in-flight only, never persisted): `version` (report), `documents` (report
counts), `queries` (query loop), `chunks` (the exact rows the seeder writes), `chunk_patient`
(leakage check, random baseline pool sizes), `gold_chunk_ids` (hit test).

`QueryOutcome` (per query, written to `results.json`): every field is either a rank that feeds a
metric, a returned-count that feeds the leg diagnostics, `leaks`, or `latency_ms_k5`.

`ChunkEmbedding` rows written by the seeder use existing columns only; no migration.

## Steps

1. Plan doc (this file). First commit.
2. `server/evals/retrieval/errors.py`: `RetrievalEvalError` base, `DatasetError`,
   `GoldResolutionError`, `EvalDependencyError`, `RetrieverDegradedError`.
3. `server/evals/retrieval/dataset.py`: pydantic models, JSON/JSONL loaders, validation, gold resolution.
4. `server/evals/retrieval/metrics.py`: pure scoring + bootstrap.
5. `server/evals/retrieval/runner.py` + `__main__.py`: preflight, seed, query, score, write evidence pack.
6. `server/evals/datasets/retrieval_v1/`: `corpus/<patient_id>/<doc_id>.txt`, `queries.jsonl`, `CARD.md`.
7. `server/evals/deterministic/test_retrieval_eval.py`: metrics, loader failure paths,
   dataset integrity (100 rows, strata, every gold resolves), runner guards and the
   degraded-retriever abort with a fake retriever. No DB and no model.
8. `server/evals/integration/test_retrieval_runner_db.py`, marked `db`/`slow`, skipped without
   `RETRIEVAL_EVAL_DATABASE_URL`. Kept under `evals/` (not `tests/`) so it does not load `tests/conftest.py`.
9. Run against a throwaway `pgvector/pgvector:pg15` container; commit `docs/benchmarks/retrieval-accuracy/`.
10. Update the audit row in `docs/benchmarks/README.md`.

## Non-happy path

- Malformed row (missing field, empty query, unknown stratum, bad JSON, negative with gold,
  positive without gold): `DatasetError` naming file, line, field, value. Run aborts before seeding.
- Duplicate `query_id` or `doc_id`: `DatasetError`.
- Gold `doc_id` unknown or owned by another patient: `DatasetError`.
- Gold quote matches 0 chunks, or appears in another document: `GoldResolutionError` listing every bad row.
- Empty dataset or empty corpus: `DatasetError`.
- Embedding model fails to load: `EvalDependencyError` with the model name. No sparse-only fallback.
- `DATABASE_URL` missing, DB unreachable, or `vector` extension missing: `EvalDependencyError`
  with host and db name only, never the password.
- The retriever's own legs swallow exceptions and return `[]`. The runner attaches a log handler
  to `app.services.hybrid_retrieval`; any `... search failed` warning during the run raises
  `RetrieverDegradedError`, and no report is written. A partial or degraded number is never published.
- Re-runs and pre-existing rows: every row the seeder writes uses an `evalr1-` id prefix, and the
  seeder deletes prior rows with that prefix first, so a re-run is idempotent. The runner refuses a
  database whose name does not contain `eval`, so it cannot write into a dev or prod database by accident.
- Concurrency: single-process, sequential; not applicable.

## Logging

- `evals.retrieval` logger: run start/end with `run_id`, dataset version, counts, durations;
  seeding counts per patient; each degraded-leg warning; every caught exception with context.
- Never logs query text or chunk text. Synthetic data, but the rule stays.

## Test criteria

Commands:
- `cd server && .venv/bin/python -m pytest evals/deterministic -p no:cacheprovider -o addopts=""` passes in under 10 s
- `cd server && RETRIEVAL_EVAL_DATABASE_URL=... .venv/bin/python -m pytest evals/integration -o addopts=""` passes
- `cd server && DATABASE_URL=... .venv/bin/python -m evals.retrieval --artifacts-dir ../docs/benchmarks/retrieval-accuracy` completes

Acceptance (from the issue):
- [x] Synthetic corpus, 8-12 fake patients, dataset card states generation method
- [x] 100 labeled queries, stratified, `server/evals/datasets/retrieval_v1`
- [x] Gold anchored to source text; survives a chunker change
- [x] Loader seeds through the existing ingestion/embedding path and resolves gold
- [x] Recall@1/5/10, MRR, bootstrap 95% CIs, per-stratum
- [x] Leakage = 0
- [x] Runner CLI with `--artifacts-dir`
- [x] Evidence pack in `docs/benchmarks/retrieval-accuracy/`
- [x] Audit row in `docs/benchmarks/README.md` updated

## Findings during implementation

Recorded here and in the PR; none are fixed in this ticket because the ticket measures as-is.

1. ORM / migration enum mismatch: `app.database.models` binds `SQLEnum(UserRole)` and
   `SQLEnum(SessionStatus)` by enum name (`'DOCTOR'`), while `000_initial` creates the Postgres
   enums with lowercase values (`'doctor'`). Any ORM insert of `User` or `Session` into a migrated
   Postgres fails. The seeder writes those three tables with SQL; chunk rows still go through
   `EmbeddingService`.
2. The dense leg's `DENSE_THRESHOLD = 0.30` empties it on 20 of 88 positive queries; median
   lists are 2 (dense) and 3 (hybrid) chunks long, so Recall@10 equals Recall@5.
3. When one leg's SQL fails, `HybridRetrievalService` logs and returns `[]` but never rolls back,
   so every later statement on that DB session fails with `InFailedSqlTransaction`. Found by the
   integration test that forces a tsquery syntax error.
4. The ivfflat index is not used for the per-patient query (the planner filters by session and
   sorts), so `ivfflat.probes = 1` does not affect these results.

## Risks and open questions

- The ivfflat index (`lists = 50`) is created by migration 001 on an empty table, and pgvector's
  default `ivfflat.probes = 1`. If the planner uses the index on a small corpus, the dense leg may
  return few rows. This is current production behavior, so it is measured as-is; the runner
  records the query plan and `ivfflat.probes` in `run-metadata.txt` so the cause is visible.
- Queries are written by the same author as the corpus, so paraphrase difficulty is bounded by
  the author. The dataset card states this.
- Path: the issue named `server/evals/datasets/retrieval_v1.jsonl`; the set needs a corpus file
  too, so it is a directory `server/evals/datasets/retrieval_v1/`.
