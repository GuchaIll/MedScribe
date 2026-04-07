# Issue #33 -- GPU-Backed Whisper Transcription Worker

**Title:** feat(inference): implement GPU-backed Whisper transcription worker

**Phase:** 3 (Python Whisper Workers) -- Steps 12-14

**Resume bullets served:** V2#2 (GPU-backed Whisper inference, sub-200ms latency), V1#4 (streaming transcription)

---

## Overview

Build a Python service for GPU-accelerated speech-to-text processing using faster-whisper (CTranslate2 backend). This is a pure Kafka consumer/producer with no HTTP endpoints and no FastAPI dependency. It is the only remaining Python service in the architecture.

## Goals

- Achieve sub-200ms transcription latency per utterance
- Support scalable processing via Kafka consumer groups
- Enable GPU and CPU inference modes
- Minimize Python surface area (inference only)

## Scope

- Directory: `services/whisper/`
- New service (no direct port, but reuses model config from existing `settings.py`)

## Tasks

### Kafka Consumer/Producer (Step 12)
- [ ] Implement Kafka consumer for `audio.voiced` topic via `confluent-kafka`:
  - [ ] Consumer group with configurable group ID
  - [ ] Offset management (auto-commit with configurable interval)
  - [ ] Graceful shutdown with offset commit
- [ ] Implement batching by `session_id`:
  - [ ] Configurable batch window (50-200ms)
  - [ ] Flush on batch size or timeout, whichever comes first
  - [ ] Group audio chunks by session for coherent transcription
- [ ] Implement Kafka producer for `transcript.segments` topic:
  - [ ] Publish transcript segments with session_id, timestamp, speaker, text, confidence
  - [ ] Message key: session_id (for partition affinity)

### Whisper Inference
- [ ] Integrate `faster-whisper` (CTranslate2 backend):
  - [ ] Model loading with configurable model size (reuse from settings.py: `whisper_model=large-v3`)
  - [ ] Device selection: `cpu` or `cuda` (from `whisper_device` config)
  - [ ] Compute type: `int8`, `float16`, `float32` (from `whisper_compute_type` config)
  - [ ] Language detection or forced language setting
- [ ] Implement inference pipeline:
  - [ ] Decode audio bytes to numpy array
  - [ ] Run transcription with word-level timestamps
  - [ ] Extract segment boundaries, text, and confidence scores
  - [ ] Format output as `TranscriptSegment` objects

### Configuration
- [ ] `config.py` with environment variable overrides:
  - [ ] `WHISPER_MODEL` (default: `large-v3`)
  - [ ] `WHISPER_DEVICE` (default: `cpu`)
  - [ ] `WHISPER_COMPUTE_TYPE` (default: `int8`)
  - [ ] `KAFKA_BOOTSTRAP_SERVERS`
  - [ ] `KAFKA_CONSUMER_GROUP`
  - [ ] `BATCH_WINDOW_MS` (default: `100`)
  - [ ] `BATCH_MAX_SIZE` (default: `10`)

### Health and Metrics (Step 13)
- [ ] Expose Prometheus metrics via HTTP endpoint:
  - [ ] `whisper_inference_seconds` (histogram) -- inference latency per batch
  - [ ] `whisper_segments_total` (counter) -- total transcript segments produced
  - [ ] `whisper_batch_size` (gauge) -- current batch size
  - [ ] `whisper_model_loaded` (gauge) -- 1 if model is loaded, 0 otherwise
- [ ] gRPC health check endpoint for Kubernetes liveness probe
- [ ] HTTP `/health` endpoint for readiness probe

### Kubernetes Deployment (Step 14)
- [ ] `Dockerfile.gpu` with CUDA base image and faster-whisper dependencies
- [ ] GPU node affinity: `nvidia.com/gpu` resource request
- [ ] KEDA ScaledObject configuration:
  - [ ] Trigger: Kafka consumer lag on `audio.voiced` topic
  - [ ] Scale range: 1-10 pods
  - [ ] Cooldown period configuration

## Acceptance Criteria

- Whisper worker transcribes audio from Kafka `audio.voiced` topic
- Transcript segments appear in `transcript.segments` within 200ms of utterance end
- Batching by session_id produces coherent per-session transcripts
- Worker runs on both CPU and GPU modes
- Prometheus metrics are accessible and accurate
- Health check endpoint responds correctly for K8s probes
- KEDA autoscaler activates based on consumer lag

## Implementation Notes

- This is the **only remaining Python service**. It is a pure Kafka consumer/producer with no HTTP endpoints (except health/metrics) and no FastAPI dependency.
- Minimal `requirements.txt`: `faster-whisper`, `confluent-kafka`, `prometheus-client`
- CTranslate2 is the only viable runtime for Whisper inference; no Go or Rust alternative exists with equivalent quality.
- Batch window trades latency for throughput: 50ms for low-latency, 200ms for high-throughput scenarios.
- Use `confluent-kafka` (librdkafka bindings) for consistency with Rust consumer.

## Files to Create

```
services/whisper/
  worker.py          -- Main entry point, Kafka consumer loop, inference dispatch
  config.py          -- Configuration with environment variable overrides
  Dockerfile.gpu     -- CUDA-based Docker image
  requirements.txt   -- faster-whisper, confluent-kafka, prometheus-client
```

## Dependencies (Python)

- `faster-whisper` -- CTranslate2-based Whisper inference
- `confluent-kafka` -- Kafka consumer/producer
- `prometheus-client` -- Prometheus metrics exposition
- `grpcio` / `grpcio-health-checking` -- gRPC health check (optional)
