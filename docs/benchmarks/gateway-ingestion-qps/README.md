# Gateway Ingestion QPS Benchmark

## Claim Scope

This benchmark is the evidence source for:

- `500 QPS` ingestion throughput
- `p50 < 1ms` gateway trigger latency

It measures only the request acceptance path:

`client -> Go gateway -> auth/session validation -> Kafka produce -> Redis seed -> 202 Accepted`

It does not measure full pipeline completion time.

## Method

- Harness: `scripts/bench-qps.sh`
- Load generator: `scripts/qps_bench.js` via k6
- Warm-up: 200 pre-warm trigger requests from the wrapper
- Sustained phase: constant-arrival-rate at the configured QPS after a 10 second warm-up phase

## Command

```bash
./scripts/bench-qps.sh \
  --url http://localhost:8080 \
  --qps 500 \
  --duration 30s \
  --vus 200 \
  --sessions 100 \
  --artifacts-dir docs/benchmarks/gateway-ingestion-qps
```

## Environment

- Date: 2026-06-04T07:02:34Z
- Host: Darwin arm64
- Docker / Compose setup: `docker compose up -d` from repository root
- Gateway target: `http://localhost:8080`

## Measured Result

- Accepted requests: `16001`
- Median trigger latency: `860µs`
- p95 trigger latency: `2.25ms`
- p99 trigger latency: `13.31ms`
- Success rate: `100%`

This run supports both published gateway claims:

- sustained ingestion at the configured `500 QPS` target
- hot-path trigger latency below `1ms` at p50

## Raw Outputs

- `run-metadata.txt`
- `k6-summary.json`
- `console.log`