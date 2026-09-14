# Benchmark Evidence

This directory is the source of truth for benchmark-backed performance claims in the repository. Every published number should map to:

- a benchmark harness committed in the repo
- a dated run record with environment details
- raw outputs produced by that harness

## Audit Status

Two distinct throughput numbers, by design — the gateway router is decoupled
from GPU-bound inference, so they are not the same measurement:

| Claim | Current public location | Harness | Artifact location | Status |
|---|---|---|---|---|
| `500 QPS` gateway ingestion throughput — **router in isolation, not end-to-end** | `README.md`, `docs/design-decisions.md` | `scripts/bench-qps.sh` | `docs/benchmarks/gateway-ingestion-qps/` | Proven on 2026-06-04 (router-only) |
| `p50 < 1ms` gateway trigger latency — **router-only** | `README.md`, `docs/design-decisions.md` | `scripts/bench-qps.sh` | `docs/benchmarks/gateway-ingestion-qps/` | Proven on 2026-06-04 (router-only) |
| `20 QPS` end-to-end pipeline throughput (GPU-bound) — **canonical pipeline number** | `README.md`, `docs/design-decisions.md` | `scripts/load-test.sh` | `docs/benchmarks/full-pipeline/` | Not supported by the 2026-06-04 local benchmark. Observed completed-iteration rate was `0.092/s` (18 completed runs over the 3m15s scenario window). |
| `23.5s` clinical-pipeline latency — **LangGraph only, excludes Whisper/pyannote** | `docs/design-decisions.md` | `scripts/load-test.sh` | `docs/benchmarks/full-pipeline/` | Not supported as a general claim. The latest local evidence shows `16.38s` for a warm single run and `42.08s` median completed iteration duration under the 10-VU benchmark. A true end-to-end number incl. the Modal Whisper+pyannote worker still needs an audio-submitting harness (`audio.ingest` → speech worker → `transcript.segments` → pipeline). |
| `85%` source-grounded retrieval accuracy — **target, not measured** | `distributed_plan2.md` | None yet | None | Target pending a retrieval eval harness. Supersedes the conflicting `98%` figure. |

## How To Record Evidence

1. Start the stack required by the target harness.
2. Run the benchmark wrapper with `--artifacts-dir` pointing to the claim directory.
3. Copy or update the claim summary in the directory `README.md`.
4. Reference that benchmark directory from public-facing docs.

## Evidence Pack Layout

Each benchmark directory should contain:

- `README.md`: benchmark method, date, claim summary, and environment notes
- `run-metadata.txt`: machine and invocation metadata written by the wrapper
- `k6-summary.json`: structured summary exported by k6
- `console.log`: raw CLI output from the benchmark run

## Commands

Gateway ingestion throughput and hot-path latency:

```bash
./scripts/bench-qps.sh \
  --url http://localhost:8080 \
  --qps 500 \
  --duration 30s \
  --vus 200 \
  --sessions 100 \
  --artifacts-dir docs/benchmarks/gateway-ingestion-qps
```

Full pipeline wall-clock latency:

```bash
./scripts/load-test.sh \
  --url http://localhost:8080 \
  --vus 10 \
  --duration 5m \
  --artifacts-dir docs/benchmarks/full-pipeline
```

## Environment Notes

The benchmark wrappers record host OS and architecture automatically. Add any benchmark-specific context that affects results to the per-run `README.md`, such as:

- Docker Desktop version
- Compose file used
- enabled LLM provider and model
- warm-up steps taken outside the harness
- whether the run was local single-host or remote

## Latest Results

Gateway ingestion benchmark run on 2026-06-04:

- host: Darwin arm64
- target: `500 QPS` for `30s`
- achieved: `16001` accepted requests over the 40 second warm-up plus sustained window
- median trigger latency: `860µs`
- p95 trigger latency: `2.25ms`
- success rate: `100%`

Full pipeline benchmark rerun on 2026-06-04:

- host: Darwin arm64
- workload: `10` max VUs with the checked-in 3m k6 scenario
- warm single-session latency: `16.38s`
- completed iterations: `18` over the `3m15s` scenario window
- completion rate threshold: passed at `100%`
- error rate threshold: passed at `0%`
- median completed iteration duration under load: `42.08s`
- p95 completed iteration duration under load: `65.46s`
- note: this evidence does not support the older `20 QPS` or unqualified `23.5s` claims