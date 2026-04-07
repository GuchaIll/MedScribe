# Issue #31 -- Rust Audio Gateway with WebSocket and VAD

**Title:** feat(audio): implement Rust audio gateway with WebSocket + VAD

**Phase:** 2 (Rust Audio Gateway + Kafka Consumers) -- Steps 8-9, 11

**Resume bullets served:** V2#1 (5K+ peak RPS), V2#2 (real-time VAD), V1#4 (sub-200ms latency)

---

## Overview

Develop a high-performance Rust service for real-time audio ingestion and server-side voice activity detection. The audio gateway accepts PCM audio frames from the browser via WebSocket, runs Silero VAD inference per frame using ONNX Runtime, and publishes voiced segments to Kafka.

## Goals

- Achieve sub-10ms VAD inference per audio frame on CPU
- Predictable sub-ms latency with zero GC pauses on the hot audio path
- Offload VAD from the browser to the server for consistency and control
- Enable scalable streaming ingestion via Kafka

## Scope

- Directory: `services/audio-gateway/`
- New service (no direct port from existing codebase)

## Tasks

### Project Setup
- [ ] Initialize Rust crate with `Cargo.toml`
- [ ] Configure `tokio` async runtime
- [ ] Set up project structure: `src/main.rs`, `src/vad.rs`, `src/kafka.rs`, `src/websocket.rs`

### WebSocket Server (Step 8)
- [ ] Implement WebSocket server using `tokio-tungstenite`:
  - [ ] Accept PCM audio frames from browser clients
  - [ ] Per-session connection management with unique session IDs
  - [ ] Ring buffer per session to accumulate audio frames
  - [ ] Handle connection lifecycle: open, message, close, error
  - [ ] Backpressure handling for slow consumers
- [ ] Publish raw audio chunks to Kafka topic `audio.raw`

### Server-Side VAD (Step 9)
- [ ] Load Silero VAD ONNX model via `ort` crate (ONNX Runtime bindings):
  - [ ] Use the native ONNX model file (not the WASM variant at `public/ort-wasm-simd-threaded.mjs`)
  - [ ] Model is approximately 2MB, designed for single-frame inference
- [ ] Run VAD inference per audio frame:
  - [ ] Speech probability threshold matching current browser behavior
  - [ ] When speech detected: buffer 800ms pre-speech audio (matching current browser `useVoiceCapture.js` behavior)
  - [ ] Accumulate frames during speech until silence detected
  - [ ] Target: sub-10ms VAD inference per frame on CPU
- [ ] Publish voiced audio segments to Kafka topic `audio.voiced`:
  - [ ] Include session_id, timestamp, audio data, duration metadata
  - [ ] Segment boundaries aligned to speech onset/offset

### Frontend WebSocket Update (Step 11)
- [ ] Update `useVoiceCapture.js` to open WebSocket connection to Rust audio gateway
- [ ] Send raw PCM audio via `AudioWorklet` processor
- [ ] Keep browser-side Web Speech API as degraded fallback when WebSocket unavailable
- [ ] Handle reconnection logic for dropped connections

### Metrics
- [ ] Expose Prometheus metrics via HTTP endpoint:
  - [ ] `audio_frames_received_total` (counter)
  - [ ] `vad_inference_seconds` (histogram)
  - [ ] `voiced_segments_total` (counter)
  - [ ] `active_sessions` (gauge)
  - [ ] `websocket_connections_total` (counter)

## Acceptance Criteria

- Audio streaming works end-to-end: browser -> WebSocket -> Rust gateway -> Kafka
- VAD correctly identifies speech segments with accuracy matching current browser-side VAD
- Voiced segments appear in Kafka `audio.voiced` topic within 10ms of speech offset
- Sub-10ms VAD inference latency per frame
- Multiple concurrent sessions handled without interference
- Prometheus metrics are accessible and accurate

## Implementation Notes

- Use `ort` crate for ONNX Runtime. The Silero VAD model supports single-frame inference and is well-tested on Linux/macOS.
- The ONNX model must be the native version, not the WASM variant. May need to download the standard Silero VAD ONNX model if only the WASM version is in the repo.
- Ring buffer per session provides pre-speech audio capture (800ms lookback) without allocating per-frame.
- Use `rdkafka` for Kafka production -- same library as the Kafka consumer service for consistency.
- Rust's zero-allocation, no-GC runtime gives predictable sub-ms latency required for the hot audio path.

## Key Risk

The `ort` crate must load the native Silero VAD ONNX model (not the WASM variant). The model is approximately 2MB and designed for single-frame inference. `onnxruntime-rs` supports this well on Linux/macOS but needs testing for the specific model version.

## Files to Create

```
services/audio-gateway/
  Cargo.toml
  src/
    main.rs         -- Entry point, tokio runtime, HTTP metrics server
    websocket.rs    -- WebSocket server, session management, ring buffers
    vad.rs          -- Silero VAD ONNX model loading and inference
    kafka.rs        -- Kafka producer for audio.raw and audio.voiced
  Dockerfile

proto/
  audio.proto       -- gRPC: StreamAudio, GetVADStatus
```

## Dependencies (Rust Crates)

- `tokio` -- async runtime
- `tokio-tungstenite` -- WebSocket server
- `ort` -- ONNX Runtime bindings for Silero VAD
- `rdkafka` -- Kafka producer (librdkafka bindings)
- `prometheus` -- metrics exposition
- `tonic` -- gRPC server/client
- `prost` -- protobuf code generation
