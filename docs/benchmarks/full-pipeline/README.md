# Full Pipeline Load Benchmark

## Claim Scope

This benchmark is the evidence source for the clinical-pipeline claims that are
actually measurable with the current harness:

- clinical-pipeline trigger-to-completion latency after transcript segments are already available
- completed pipeline rate under the `tests/load/pipeline_test.js` 10-VU scenario

It is not evidence for a Whisper-inclusive end-to-end speech number.

**Important — what this measures and does not measure.** It exercises the
request path from **pipeline trigger** (transcript segments already provided)
through background LangGraph execution, polling status until completion. It
does **NOT** include audio transcription or diarization: no audio is submitted,
and the Modal Whisper + pyannote worker is not on this path. So this harness
backs a **LangGraph-pipeline-only** number, not the résumé bullet's
"end-to-end latency via Whisper and speaker diarization."

### Measuring true end-to-end (incl. Whisper + pyannote)

The spec's end-to-end claim is **not measurable with the current harness**. To
back it, a new audio-submitting harness is required:

1. Set `SPEECH_PROVIDER=remote_http` and `SPEECH_REMOTE_URL` to the deployed
   Modal worker URL (`infra/modal/medscribe_speech_worker.py`); authenticate Modal.
2. Drive audio through the ingress path: audio segments → `audio.ingest` → Go
   `audioproxy` → Modal `/process-audio` (Whisper + pyannote) →
   `transcript.segments` → pipeline trigger → status poll.
3. Record wall-clock from first audio segment to pipeline completion.

Until that harness exists and is run, no doc should assert a Whisper-inclusive
end-to-end latency number.

## Method

- Harness: `scripts/load-test.sh`
- Load generator: `tests/load/pipeline_test.js` via k6
- Workload: authenticated session creation, pipeline trigger, repeated status polling until completion or timeout

## Command

```bash
./scripts/load-test.sh \
  --url http://localhost:8080 \
  --vus 10 \
  --duration 5m \
  --artifacts-dir docs/benchmarks/full-pipeline
```

## Environment

- Date: 2026-06-04T09:04:57Z
- Host: Darwin arm64
- Compose setup: `docker compose up -d db redis kafka kafka-init gateway api`
- Warm-up notes:
   - LangGraph dependency stack pinned to a compatible checkpoint package set.
   - Graph node IDs renamed to avoid LangGraph state-key collisions.
   - Embedding-service grounding retries now memoize model-load failure, preventing per-candidate BioLord retry stalls.

## Measured Result

Successful rerun on 2026-06-04:

- Warm single-session trigger-to-completion latency: `16.38s`
- Warm single-session node timings:
   - `clean_transcription`: `3.80s`
   - `extract_candidates`: `6.28s`
   - `run_diagnostic_reasoning`: `2.50s`
   - `retrieve_evidence`: `0.80s`
- 10-VU k6 scenario result: `18` completed iterations over the `3m15s` scenario window
- k6 `pipeline_completed_rate`: `100%` (`rate>0.8` passed)
- k6 `pipeline_error_rate`: `0%` (`rate<0.05` passed)
- Trigger p99 threshold: passed (`p(99)=4.75ms`, threshold `<200ms`)
- Status poll p95 threshold: passed in terminal summary (`p(95)=5ms`, threshold `<100ms`)
- Median end-to-end iteration duration under load: `42.08s`
- p95 end-to-end iteration duration under load: `65.46s`

Interpretation:

- The old `23.5s` unqualified pipeline-latency claim is not supported by this evidence pack.
- A warm single local pipeline run completed in `16.38s`, but under the 10-VU benchmark the median completed iteration was `42.08s`.
- The previous `20 QPS` pipeline-throughput claim is also not supported by this run; the observed completed-iteration rate was `0.092/s`.

## Root Causes Fixed Before This Rerun

Two Python-service issues had to be fixed before a successful rerun was possible:

```text
1. LangGraph import / checkpoint compatibility:
    TypeError: Reviver.__init__() got an unexpected keyword argument 'allowed_objects'

2. Graph construction failure:
    ValueError: 'diagnostic_reasoning' is already being used as a state key
```

After those were fixed, the dominant latency moved to extraction-time grounding. The final improvement that made the benchmark viable was caching embedding-model load failure so the offline BioLord model did not retry on every candidate fact.

## Threshold Note

Use `terminal-run.log` / `console.log` as the threshold source of truth for this run. The exported `k6-summary.json` contains the correct raw metric values, but its custom-metric `thresholds` booleans were not reliable in this wrapper run even when the terminal summary showed passing thresholds.

## Raw Outputs

- `run-metadata.txt`
- `k6-summary.json`
- `console.log`
- `terminal-run.log`