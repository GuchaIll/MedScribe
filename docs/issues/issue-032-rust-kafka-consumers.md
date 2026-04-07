# Issue #32 -- Rust Kafka Consumer Routing Layer

**Title:** feat(kafka): implement Rust-based Kafka consumer routing layer

**Phase:** 2 (Rust Audio Gateway + Kafka Consumers) -- Step 10

**Resume bullets served:** V2#1 (5K+ peak RPS), V1#4 (sub-200ms latency)

---

## Overview

Build a high-throughput Rust Kafka consumer framework that routes messages from multiple Kafka topics to the appropriate downstream services via gRPC. The Rust consumer is the high-throughput entry point that handles backpressure, batching, and delivery semantics. The Go orchestrator and Python whisper-worker are the compute-heavy backends.

## Goals

- Handle 5K+ messages per second with predictable latency
- Route messages from multiple Kafka topics to appropriate services
- Provide exactly-once delivery semantics where required
- Manage backpressure between Kafka and downstream gRPC services

## Scope

- Directory: `services/kafka-consumers/`
- New service (no direct port from existing codebase)

## Tasks

### Project Setup
- [ ] Initialize Rust crate with `Cargo.toml`
- [ ] Configure `tokio` async runtime
- [ ] Set up project structure: `src/main.rs`, `src/consumer.rs`, `src/router.rs`

### Kafka Consumer Framework
- [ ] Implement `rdkafka` consumer group with configurable topic subscriptions:
  - [ ] `audio.raw` -- route to audio-gateway VAD pipeline (or process in-place)
  - [ ] `transcript.segments` -- forward to Go orchestrator via gRPC `tonic` client
  - [ ] `pipeline.trigger` -- forward to Go orchestrator via gRPC `tonic` client
- [ ] Implement consumer configuration:
  - [ ] Consumer group ID management
  - [ ] Partition assignment strategy
  - [ ] Offset management (auto-commit vs manual)
  - [ ] Configurable poll timeout and batch size

### Message Routing
- [ ] Implement topic-based routing:
  - [ ] `audio.raw` messages -> audio-gateway VAD processing
  - [ ] `transcript.segments` messages -> Go orchestrator `RunPipeline` or `AppendTranscript` gRPC call
  - [ ] `pipeline.trigger` messages -> Go orchestrator `RunPipeline` gRPC call
  - [ ] `pipeline.results` messages -> API gateway for WebSocket/poll delivery
- [ ] Configurable routing table (topic -> handler mapping)
- [ ] Dead letter queue for unroutable or failed messages

### gRPC Client
- [ ] Implement `tonic` gRPC client for Go orchestrator:
  - [ ] `RunPipeline` call
  - [ ] `ResumeFromCheckpoint` call
  - [ ] Connection pooling and retry logic
  - [ ] Timeout configuration per call type
- [ ] Implement `tonic` gRPC client for Python whisper-worker (if needed for health checks)

### Backpressure and Reliability
- [ ] Implement backpressure handling:
  - [ ] Pause consumption when downstream service is slow or unavailable
  - [ ] Resume when downstream service recovers
  - [ ] Configurable in-flight message limit
- [ ] Implement batching:
  - [ ] Configurable batch size and batch window
  - [ ] Flush on batch size or timeout, whichever comes first
- [ ] Implement exactly-once delivery semantics:
  - [ ] Idempotent message processing
  - [ ] Transactional Kafka commits where required
- [ ] Implement graceful shutdown:
  - [ ] Drain in-flight messages before stopping
  - [ ] Commit final offsets

### Metrics
- [ ] Expose Prometheus metrics via HTTP endpoint:
  - [ ] `kafka_messages_consumed_total` (counter, by topic)
  - [ ] `kafka_consumer_lag` (gauge, by topic and partition)
  - [ ] `grpc_requests_total` (counter, by target service)
  - [ ] `grpc_request_duration_seconds` (histogram, by target service)
  - [ ] `message_processing_errors_total` (counter, by topic and error type)
  - [ ] `dead_letter_messages_total` (counter)

## Acceptance Criteria

- Consumer successfully reads from all configured Kafka topics
- Messages are correctly routed to Go orchestrator via gRPC
- Consumer handles 5K+ messages per second without message loss
- Backpressure correctly pauses/resumes consumption
- Graceful shutdown completes without message loss
- Prometheus metrics are accessible and accurate
- Dead letter queue captures unprocessable messages

## Implementation Notes

- Use `rdkafka` (librdkafka bindings) over pure-Rust alternatives. `librdkafka` is battle-tested at 5K+ RPS with exactly-once semantics. Pure Rust alternatives (`kafka-rust`) lack feature parity.
- Rust's zero-allocation, no-GC runtime ensures predictable latency under high throughput.
- Each topic handler runs in its own tokio task for isolation.
- gRPC connection pooling via `tonic` channel with configurable max concurrent requests.
- Message deserialization should be zero-copy where possible (reference Kafka message bytes directly).

## Files to Create

```
services/kafka-consumers/
  Cargo.toml
  src/
    main.rs       -- Entry point, tokio runtime, consumer group setup
    consumer.rs   -- rdkafka consumer wrapper, offset management
    router.rs     -- Topic-based message routing to handlers
    grpc.rs       -- tonic gRPC client for Go orchestrator
    metrics.rs    -- Prometheus metrics exposition
  Dockerfile
```

## Dependencies (Rust Crates)

- `tokio` -- async runtime
- `rdkafka` -- Kafka consumer (librdkafka bindings)
- `tonic` -- gRPC client
- `prost` -- protobuf code generation
- `prometheus` -- metrics exposition
- `serde` / `serde_json` -- message deserialization
