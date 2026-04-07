# Issue #36 -- Metrics and Distributed Tracing

**Title:** feat(observability): implement metrics and distributed tracing

**Phase:** 7 (Observability) -- Steps 28-30

**Resume bullets served:** V1#5 (Prometheus + OpenTelemetry, token throughput)

---

## Overview

Introduce comprehensive observability across all services using Prometheus for metrics and OpenTelemetry for distributed tracing. Deploy Grafana for dashboards and Jaeger for trace visualization.

## Goals

- Enable real-time system monitoring across all services
- Provide end-to-end distributed tracing from audio ingestion through pipeline execution to transcription
- Visualize LLM latency, token throughput, pipeline execution, and Kafka lag

## Scope

- Applies to all services:
  - Go API gateway (`services/api/`)
  - Go orchestrator (`services/orchestrator/`)
  - Rust audio-gateway (`services/audio-gateway/`)
  - Rust kafka-consumers (`services/kafka-consumers/`)
  - Python whisper-worker (`services/whisper/`)
- Infrastructure: `docker-compose.yml`

## Tasks

### Prometheus Metrics (Step 28)

#### Go API Gateway
- [ ] `http_requests_total` (counter, labels: method, path, status_code)
- [ ] `http_request_duration_seconds` (histogram, labels: method, path)
- [ ] `active_sessions` (gauge) -- currently active transcription sessions
- [ ] `active_websocket_connections` (gauge)
- [ ] Use `prometheus/client_golang` library
- [ ] Expose at `GET /metrics` endpoint

#### Go Orchestrator
- [ ] `pipeline_duration_seconds` (histogram, labels: node_name) -- per-node execution time
- [ ] `pipeline_total_duration_seconds` (histogram) -- full pipeline execution time
- [ ] `llm_requests_total` (counter, labels: provider, model, status)
- [ ] `llm_latency_seconds` (histogram, labels: provider, model)
- [ ] `llm_tokens_total` (counter, labels: provider, model, type=[prompt|completion])
- [ ] `pipeline_runs_total` (counter, labels: status=[completed|failed|paused])
- [ ] `checkpoint_writes_total` (counter)
- [ ] `repair_loop_iterations_total` (counter)

#### Rust Audio Gateway
- [ ] `audio_frames_received_total` (counter)
- [ ] `vad_inference_seconds` (histogram)
- [ ] `voiced_segments_total` (counter)
- [ ] `active_audio_sessions` (gauge)
- [ ] Use `prometheus` Rust crate
- [ ] Expose at HTTP `/metrics` endpoint

#### Rust Kafka Consumers
- [ ] `kafka_messages_consumed_total` (counter, labels: topic)
- [ ] `kafka_consumer_lag` (gauge, labels: topic, partition)
- [ ] `grpc_forwarded_total` (counter, labels: target_service)
- [ ] `message_processing_errors_total` (counter, labels: topic, error_type)

#### Python Whisper Worker
- [ ] `whisper_inference_seconds` (histogram)
- [ ] `whisper_segments_total` (counter)
- [ ] `whisper_batch_size` (gauge)
- [ ] `whisper_model_loaded` (gauge)
- [ ] Use `prometheus_client` library

### OpenTelemetry Distributed Tracing (Step 29)

#### Go Services
- [ ] Integrate `go.opentelemetry.io/otel` SDK:
  - [ ] Span per pipeline node execution (parent span: full pipeline run)
  - [ ] Span per LLM API call (includes provider, model, token counts as attributes)
  - [ ] Span per database query
  - [ ] Span per Redis operation
- [ ] Propagate trace context through:
  - [ ] HTTP request headers (W3C Trace Context)
  - [ ] gRPC metadata
  - [ ] Kafka message headers

#### Rust Services
- [ ] Integrate `opentelemetry` Rust crate:
  - [ ] Span per audio frame processing
  - [ ] Span per VAD inference
  - [ ] Span per Kafka message consumption and routing
- [ ] Propagate trace context through Kafka message headers

#### Python Whisper Worker
- [ ] Integrate `opentelemetry-sdk`:
  - [ ] Span per inference batch
  - [ ] Span per Whisper model call
- [ ] Extract trace context from Kafka message headers

#### Cross-Service Trace Propagation
- [ ] Trace context propagated through Kafka message headers:
  - [ ] Producer injects `traceparent` header
  - [ ] Consumer extracts and continues trace
- [ ] End-to-end trace: browser audio -> Rust gateway -> Kafka -> Python whisper -> Kafka -> Rust consumer -> Go orchestrator -> LLM API -> PostgreSQL

### Grafana and Jaeger Deployment (Step 30)

#### docker-compose.yml Additions
- [ ] Add Prometheus service:
  - [ ] Image: `prom/prometheus`
  - [ ] Scrape config targeting all service metrics endpoints
  - [ ] Retention period configuration
- [ ] Add Grafana service:
  - [ ] Image: `grafana/grafana`
  - [ ] Auto-provisioned Prometheus data source
  - [ ] Pre-built dashboards (see below)
- [ ] Add Jaeger service:
  - [ ] Image: `jaegertracing/all-in-one`
  - [ ] OTLP receiver for OpenTelemetry traces
  - [ ] UI exposed on port 16686

#### Pre-Built Grafana Dashboards
- [ ] **LLM Performance**: latency by provider (p50, p95, p99), token throughput rate, error rate, cost estimate
- [ ] **Pipeline Execution**: node waterfall (duration per node), pipeline success/failure rate, repair loop frequency
- [ ] **Kafka Health**: consumer lag per topic, message throughput, partition distribution
- [ ] **Audio Processing**: VAD latency histogram, frames per second, active sessions
- [ ] **System Overview**: HTTP request rate, error rate, active sessions, resource utilization

## Acceptance Criteria

- Grafana dashboards show LLM latency, token throughput, pipeline node waterfall, and Kafka consumer lag
- Jaeger shows end-to-end traces from Rust audio-gateway through Go orchestrator to Python whisper-worker
- Trace context is preserved across Kafka message boundaries
- All services expose `/metrics` endpoint with documented metrics
- Prometheus successfully scrapes all service endpoints

## Implementation Notes

- Standardize metric naming across services using Prometheus naming conventions (snake_case, unit suffix)
- Use histogram buckets appropriate for each metric (e.g., LLM latency: 0.1s-30s range, VAD: 0.001s-0.1s range)
- Grafana dashboards stored as JSON in `monitoring/dashboards/` for version control
- Jaeger receives traces via OTLP protocol (port 4317 for gRPC, 4318 for HTTP)
- Trace sampling rate should be configurable (100% in dev, 10% in production)

## Files to Create/Modify

```
services/api/telemetry/
  prometheus.go     -- Prometheus metric definitions and registration
  otel.go           -- OpenTelemetry tracer provider and span helpers

monitoring/
  prometheus.yml    -- Prometheus scrape configuration
  dashboards/
    llm.json        -- LLM performance dashboard
    pipeline.json   -- Pipeline execution dashboard
    kafka.json      -- Kafka health dashboard
    audio.json      -- Audio processing dashboard
    overview.json   -- System overview dashboard

docker-compose.yml  -- Add prometheus, grafana, jaeger services
```

## Dependencies

### Go
- `github.com/prometheus/client_golang` -- Prometheus metrics
- `go.opentelemetry.io/otel` -- OpenTelemetry SDK
- `go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc` -- OTLP trace exporter

### Rust
- `prometheus` crate -- metrics exposition
- `opentelemetry` crate -- tracing SDK

### Python
- `prometheus-client` -- metrics exposition
- `opentelemetry-sdk` -- tracing SDK
