# Retrieval accuracy baseline (#104)

Recall@k and MRR for the retriever on `main`, `HybridRetrievalService.search_chunks_for_patient`
(patient-scoped pgvector cosine + Postgres full text, fused with RRF), on a 100-query labeled
synthetic eval set. This is the pre-refactor baseline that #98 (T3) has to beat.

- Harness: [`server/evals/retrieval/`](../../../server/evals/retrieval/)
- Dataset: [`server/evals/datasets/retrieval_v1/`](../../../server/evals/datasets/retrieval_v1/) ([card](../../../server/evals/datasets/retrieval_v1/CARD.md))
- Raw results: [`results.json`](results.json) (aggregates plus every query), [`run-metadata.txt`](run-metadata.txt), [`console.log`](console.log)
- Run date: 2026-11-12

## Result

**Recall@5 = 94.3% (95% CI 88.6-98.9%), MRR@10 = 0.785, on 88 positive queries. Zero cross-patient leakage.**

| | n | Recall@1 | Recall@5 | Recall@10 | MRR@10 |
|---|---|---|---|---|---|
| **Hybrid (as shipped)** | 88 | 0.670 [0.568, 0.761] | **0.943** [0.886, 0.989] | 0.943 [0.886, 0.989] | 0.785 [0.716, 0.851] |
| exact_term | 22 | 0.818 | 1.000 | 1.000 | 0.898 |
| paraphrase | 22 | 0.636 | **0.773** | 0.773 | 0.682 |
| numeric | 22 | 0.591 | 1.000 | 1.000 | 0.761 |
| medication | 22 | 0.636 | 1.000 | 1.000 | 0.799 |
| Random draw from the patient's pool | | 0.113 | 0.524 | 0.945 | |
| Dense leg alone | 88 | 0.443 | 0.636 | 0.636 | 0.528 |
| Sparse leg alone | 88 | 0.716 | 0.898 | 0.898 | 0.794 |

Brackets are 95% percentile-bootstrap intervals (2000 resamples, seed 104). Per-stratum
intervals are in `results.json`; with n = 22 they are wide (paraphrase Recall@5: 0.591-0.955).

Negatives (12 queries whose answer is not in that patient's records): the retriever returned at
least one chunk for 41.7% of them. It has no "no source" outcome; the other 58.3% came back empty
because no chunk passed the dense threshold and no keyword matched.

Latency for one `top_k=5` call, in-process (query embedding + both SQL legs + RRF), Apple M-series
with MPS, local Docker Postgres: p50 20.8 ms, p95 71.0 ms. These are not service latencies.

## How to read this number

1. **The pool is small.** Each patient has 9-13 chunks (4 documents). A random pick of 5 chunks
   already finds the answer 52.4% of the time, so the retriever adds about 42 points over chance at
   k = 5. Recall@10 is close to meaningless here: random is 94.5%. Real patient records have far
   more chunks, and recall will be lower there.
2. **Most of the hybrid number comes from the keyword leg.** Sparse alone reaches 0.898; dense alone
   0.636. The dense leg drops every row with cosine similarity below `DENSE_THRESHOLD = 0.30`, and
   returned nothing at all for 20 of 88 positive queries. Median chunks returned per call: 3 for
   `top_k=5` and also 3 for `top_k=10`, which is why Recall@10 equals Recall@5.
3. **Paraphrase is the weak stratum (77.3%).** Questions that share no words with the answer
   depend on the dense leg, which is the leg the threshold starves.
4. **Same author for corpus and queries.** Paraphrase difficulty is bounded by one writer. See the card.
5. **Retriever measured with an ingested corpus, not the live pipeline end to end.** No code under
   `server/app/` writes `chunk_embeddings` today; the eval seeds it through the production
   functions (`segment.chunk_documents` -> `EmbeddingService.store_chunk_embeddings_batch`). In the
   running app the table is empty and this retriever returns nothing.

## Method

1. `alembic upgrade head` on a throwaway `pgvector/pgvector:pg15` container (pgvector 0.8.7), so the
   real ivfflat and GIN indexes exist.
2. 40 synthetic documents for 10 fake patients are chunked by `app.agents.nodes.segment.chunk_documents`
   (500 characters, 50 overlap) and embedded with BioLord-2023-M (768-d) through
   `EmbeddingService.store_chunk_embeddings_batch`. One session per patient.
3. Gold labels are `{doc_id, quote}`. At load time each quote is resolved to the chunks that contain
   it; a quote that is missing, split across a chunk boundary, or present in two documents fails the
   load. Labels survive a chunker change (#98).
4. Each query runs `search_chunks_for_patient` twice, with `top_k=5` (Recall@1, Recall@5) and
   `top_k=10` (Recall@10, MRR@10). RRF over legs truncated at `2k` is not prefix-stable, so top 5 of
   a `k=10` call is not what a `k=5` caller gets. Production `AssistantService` uses `top_k=6`.
5. Each leg is also called alone (`k=10`) for the leg rows. Both legs are plain `ORDER BY ... LIMIT`,
   so their top 5 is a prefix of their top 10.
6. Leakage: every returned chunk is checked against the patient it was seeded for.
7. Abort rule: the service catches exceptions in each leg and returns `[]`. The runner watches the
   service's logger and aborts with no report if any leg fails, so a degraded run is never published.

The planner did not use the ivfflat index (`dense_plan_uses_ivfflat=false` in `run-metadata.txt`):
with a per-session filter it scans the session's rows and sorts, so `ivfflat.probes = 1` did not
affect these results. At larger per-patient volumes it might.

## Reproduce

```bash
docker run -d --rm --name medscribe-eval-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=medscribe_eval -p 55432:5432 pgvector/pgvector:pg15
cd server
export DATABASE_URL=postgresql://postgres:postgres@localhost:55432/medscribe_eval
alembic upgrade head
python -m evals.retrieval --artifacts-dir ../docs/benchmarks/retrieval-accuracy
```

The runner refuses any database whose name does not contain `eval`. Re-runs replace their own
`evalr1-` rows. Exit codes: 0 ok, 2 dataset error, 3 missing dependency, 4 retriever degraded, 1 other.
