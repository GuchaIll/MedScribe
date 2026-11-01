# T0 isolation probe (#91)

Paired probe for the #91 exit criterion: does one session ingesting an 8-page
PDF slow down other sessions' requests?

- Script: [`scripts/probe_isolation.py`](../../../scripts/probe_isolation.py)
- Raw results: [`main.json`](main.json), [`branch.json`](branch.json)
- Run date: 2026-10-21

## Result

**Threshold not met on the branch (1.48x and 1.30x against 1.2x).** The
cross-session stall itself is gone: ingesting p99 `/transcribe` dropped from
101.5 s to 17.9 ms. The threshold was not loosened.

| Metric | main idle | main ingesting | main ratio | branch idle | branch ingesting | branch ratio |
| --- | --- | --- | --- | --- | --- | --- |
| `/transcribe` p50 | 8.5 ms | 82,218 ms | | 7.3 ms | 3.6 ms | |
| `/transcribe` p99 | 496.7 ms | 101,513 ms | **204x** | 12.1 ms | 17.9 ms | **1.48x** |
| `/transcribe` max | 502.7 ms | 102,014 ms | | 12.5 ms | 72.7 ms | |
| `/assistant` p50 | 219.1 ms | 85,718 ms | | 371.6 ms | 521.9 ms | |
| `/assistant` p95 | 503.0 ms | 103,094 ms | **205x** | 657.8 ms | 856.6 ms | **1.30x** |
| `/assistant` stdev (idle) | | | | 132.4 ms | | |
| errors | 0 | 0 | | 0 | 0 | |
| 8-page upload duration | | 104-120 s | | | 51 s | |
| `X-MedScribe-Offload` | | (absent) | | | `process` | |

Thresholds (fixed before the run): ingesting p99 `/transcribe` <= 1.2x idle,
ingesting p95 `/assistant` <= 1.2x idle.

What is left on the branch is CPU contention, not loop blocking. The branch's
idle `/transcribe` p99 is 12 ms, so a 6 ms absolute rise reads as 1.48x.
`/assistant` p95 rose 199 ms, about 1.5 idle standard deviations. The parent
(torch embeddings) and the OCR child share a 4-CPU quota. This is one run per
side; run-to-run variance was not measured.

## Setup

- One uvicorn worker per run, no `--reload`, container `--cpus 4`, image
  `medscribe-api:latest` (Python 3.11, poppler, RapidOCR 1.4.4) with each
  checkout's `server/` mounted. Postgres `pgvector/pgvector:pg15`, Redis 7.
- `alembic upgrade heads`, because `main` has two heads (fixed in #99).
- Load is open-loop: session A `/transcribe` at 2 rps, session B `/assistant`
  at 1 rps, 60 s per phase. Phase 2 adds session C uploading the PDF
  back to back, starting 2 s before measurement.
- The PDF is 8 image-only pages built from the repo's sample images
  (`server/tests/ocr_examples/*.jpg`), so every page goes through RapidOCR.
  No PHI.
- Warm-up before phase 1: one `/assistant` (loads the embedding model) and one
  upload (loads OCR models).
- Groq returned 404 `model_not_found` for the configured models in both runs,
  so the LLM calls failed fast in both. OCR, classification fallback, and field
  extraction ran the same way on both sides.

## Branch iterations (same probe, intermediate results)

| Branch state | `/transcribe` p99 idle / ingesting | `/assistant` p95 idle / ingesting | Cause found |
| --- | --- | --- | --- |
| OCR in pool | 472 ms / 125,292 ms | 540 ms / 125,596 ms | Every spawn child died at import: `main.py` put `server/app` on `sys.path`, and `app/logging.py` shadowed stdlib `logging`. Jobs fell back to a thread (header `thread_fallback`). |
| + `sys.path` fix | 547 ms / 100,252 ms | 603 ms / 102,380 ms | OCR ran in the child (header `process`), but `/assistant` ran sync embedding + LLM on the loop and slowed under CPU contention. |
| + `/assistant` off the loop | 15.7 ms / 3,240 ms | 646 ms / 4,144 ms | ONNX in the child sized its thread pool to 12 visible cores under a 4-CPU quota. |
| + `OCR_CHILD_THREADS=2` (final) | 12.1 ms / 17.9 ms | 658 ms / 857 ms | Remaining CPU sharing. |

## Memory (branch, final run, peak RSS)

| Process | Peak RSS |
| --- | --- |
| API parent (uvicorn, torch embedding model loaded) | 1,209 MB |
| OCR child (RapidOCR models loaded, 2 threads) | 333 MB |
| compile child (idle in this probe) | not sampled separately |
| multiprocessing resource tracker | 10 MB |

## Reproduce

```bash
docker network create t91net
docker run -d --name t91-db --network t91net -e POSTGRES_DB=medscribe \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg15
docker run -d --name t91-redis --network t91net redis:7-alpine
docker run -d --name t91-api --network t91net -p 3092:3001 --cpus 4 \
  -v "$PWD/server:/app" --env-file .env \
  -e DATABASE_URL=postgresql://postgres:postgres@t91-db:5432/medscribe \
  -e REDIS_URL=redis://t91-redis:6379/0 medscribe-api:latest \
  sh -c "alembic upgrade heads && uvicorn main:app --host 0.0.0.0 --port 3001"
python scripts/probe_isolation.py --base-url http://localhost:3092 \
  --label branch --out docs/benchmarks/t0-isolation/branch.json
```
