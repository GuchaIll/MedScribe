# MedScribe — Engineering Decisions

## LangGraph for Clinical Orchestration Over a Custom State Machine

LangGraph was selected over a hand-rolled pipeline because it provides native state serialisation, conditional edge routing, and interrupt/resume semantics. The 16-node pipeline runs on the Python backend, triggered by Kafka messages from the Go gateway.

**AgentContext dependency injection:** Each node receives its services -- `LLMClient`, `EmbeddingService`, `PatientRepository` -- via an injected `AgentContext` dataclass rather than importing singletons. `make_node(fn, ctx)` wraps each node function and detects whether it accepts a second `ctx` parameter; nodes that do receive it, context-free nodes do not. This makes every node independently unit-testable.

```python
# Context-aware node signature
def validate_and_score_node(state: GraphState, ctx: AgentContext) -> GraphState:
    embedding_service = ctx.embedding_service
    patient_repo = ctx.patient_repo
    ...

# Context-free node
def greeting_node(state: GraphState) -> GraphState:
    ...
```

**Interrupt/resume mechanism:** `build_graph()` accepts `enable_interrupts=True`, which compiles the graph with `interrupt_before=["human_review_gate"]`. When the graph reaches the node boundary before `human_review_gate`, it pauses. Resume triggers are published via Kafka.

**Current status:** The pipeline consumer currently calls `WorkflowEngine(enable_interrupts=False)`. The infrastructure is in place; enabling it requires changing one parameter and adding a resume Kafka topic.

---

## Groq Inference for Clinical Reasoning, While Transcription Remains Browser-Based

The current deployed speech path is browser-side Silero VAD plus the Web Speech API. Whisper and pyannote-related configuration exists in the repo, but those models are not on the active transcription request path today. Rather than blocking the rest of the product on local speech-model packaging issues, Groq's hosted Llama 4 Scout 17B (`llama-4-scout-17b-16e-instruct`) was adopted as the inference backend for the clinical reasoning pipeline.

The important clarification is scope: pipeline latency discussion here refers to the LangGraph clinical pipeline after transcript segments already exist. It is not a Whisper or diarization benchmark. The reproducible evidence for this path is tracked in `docs/benchmarks/full-pipeline/`. The current local evidence pack shows a warm single pipeline run at `16.38s`, while the 10-VU load benchmark had a `42.08s` median completed iteration duration. That evidence does not support the older unqualified `23.5s` or `20 QPS` statements. This produced an operational benefit as well: the server deploys on CPU-only machines with no CUDA dependency (`requirements.docker.txt` uses `torch==2.2.0+cpu`), significantly reducing the infrastructure footprint. SOAP note generation runs in approximately 1-3 seconds. A dedicated Whisper + pyannote speech service remains the intended next step for transcription quality and role detection.

LLM is invoked in four nodes: `diagnostic_reasoning`, `repair`, `field_extractor` (OCR disambiguation), and `generate_note`. All other reasoning -- validation, clinical suggestions, conflict detection -- is deterministic.

---

## Silero VAD Gating the Web Speech API

The Web Speech API alone misses the first 100–400ms of each utterance because the browser delays recognition start until audio crosses a noise threshold. Silero VAD (via `@ricky0123/vad-react`) runs in a Web Worker and fires `onSpeechStart` at approximately 50–100ms after voice onset, at which point the parent thread initialises the recognition session. An 800ms pre-speech audio pad is buffered so the recogniser has framing context for the full utterance.

This browser-side VAD remains useful even after a server-side speech service lands. The plan is to keep Silero VAD as the utterance boundary detector in the browser, send voiced audio segments to Whisper for transcription, use pyannote for diarized speaker segmentation, and keep browser speech synthesis for audio playback. A neural output voice is out of scope for now.

---

## Whisper + pyannote Role-Detection Service (built on Modal, not yet the default path)

**Status (2026-06-04):** This service is **implemented** as a Modal GPU worker
(`infra/modal/medscribe_speech_worker.py`) — faster-whisper (`large-v3`,
CUDA/float16) + pyannote diarization behind a FastAPI `/process-audio`
endpoint, reached from the Go gateway via `audioproxy`. It is **not yet the
default live transcription path**: `SPEECH_PROVIDER` defaults to `noop` and the
browser Web Speech API remains the live source until the provider is switched
to `remote_http` and pointed at the Modal URL. Note the deployment target is
**Modal serverless**, not the K8s/KEDA GPU worker pool sketched in
`distributed_plan2.md` — that plan is superseded for speech inference.

The original intended architecture was to improve transcription quality and clinician/patient labeling with a server-side speech stack rather than relying purely on browser recognition heuristics. Role detection is clinically meaningful: medication instructions, symptom descriptions, and assessment language carry very different semantics depending on who said them.

The service keeps the current UX shape:

- Silero VAD stays in the browser for utterance start/end detection
- voiced audio segments are sent to the backend
- Whisper produces the authoritative transcript text
- pyannote produces diarized speaker segments
- a session-level role resolver maps diarized speakers to `Clinician` / `Patient`
- browser speech synthesis remains the only output voice path

The detailed phased plan lives here: [whisper_pyannote_role_detection_plan.md](./whisper_pyannote_role_detection_plan.md)

---

## Go API Gateway with Strangler-Fig Migration

The monolithic Python FastAPI server was decomposed using a strangler-fig pattern. A Go API gateway (`services/api/`) now owns:

- **Authentication**: JWT-based registration and login via golang-jwt/v5
- **Session management**: CRUD operations with pgx/v5 connection pooling (50/50 min/max connections)
- **Request routing**: chi v5 mux with middleware chaining (JWT validation, Prometheus metrics, structured logging via zap)
- **Pipeline triggering**: Kafka publish with async return
- **Pipeline status**: Redis reads for real-time progress polling

Remaining endpoints (OCR, clinical reasoning, record generation, LLM provider management) are reverse-proxied to the Python backend. The gateway is the single entry point for all client traffic on port 8080.

**One image, multiple modes (split-image worker topology):** The Kafka consumers that bridge to Python are *not* a separate codebase — the Go service is one binary that selects its role via `--mode` (`gateway`, `pipeline-worker`, `ocr-worker`, `audio-worker`, or `all`). In production each runs as its own Kubernetes Deployment off the same image, so a slow pipeline backs up only the `pipeline-worker` (scaled on Kafka lag via KEDA) without affecting the gateway's request path or the OCR/audio lanes. `--mode=all` runs everything in one process and is the default for local dev / `docker compose`. Manifests live in `infra/k8s/`. This is a deliberate strangler-fig step: the consumers are already independently deployable and scalable without yet being separate services/repos.

**Why Go over extending Python:** The pipeline trigger endpoint is the highest-throughput path. Go's goroutine model, static compilation, and minimal GC pause times make it better suited for a high-concurrency request router than Python's asyncio. The Python backend remains optimal for LangGraph orchestration and ML workloads. This split is exactly what lets the two throughput numbers diverge: the **gateway router ingests ~500 QPS in isolation** (proven 2026-06-04, router-only — see `docs/benchmarks/`), while the **full clinical pipeline is inference-bound and must be described from benchmark evidence rather than a fixed headline QPS number**. Decoupling the API from inference via Kafka is what keeps the router fast under load even though the pipeline is slower.

**In-process session cache:** A `sync.Map`-based TTL cache (`pkg/cache/cache.go`) with 1-hour expiry eliminates PostgreSQL round-trips on the hot path. On cache miss, the gateway queries PG and populates the cache. A background reaper goroutine evicts expired entries every 30 minutes. The reproducible harness and artifact location for hot-path trigger latency are tracked in `docs/benchmarks/gateway-ingestion-qps/`.

---

## Kafka Event Bus Over Synchronous HTTP Pipeline Trigger

Pipeline execution is decoupled from the HTTP request cycle via Apache Kafka 4.2 (KRaft mode, no ZooKeeper). When the gateway receives a pipeline trigger request:

1. Validates session (cache -> PG fallback)
2. Seeds pipeline status in Redis via async goroutine (fire-and-forget)
3. Produces a message to `pipeline.trigger` topic and returns `202 Accepted`

**Producer configuration rationale:**
- `acks=1` (leader acknowledgement only): Acceptable for pipeline triggers because the trigger is idempotent and the single-broker Docker setup makes `acks=all` equivalent to `acks=1` anyway. Eliminates fsync blocking on the hot path.
- Async delivery (`nil` delivery channel): Delivery reports are consumed by a background `drainEvents()` goroutine that logs failures via `fmt.Printf`. The gateway does not block on broker acknowledgement.
- Micro-batching (`linger.ms=10`, `batch.size=64KB`): Amortises broker round-trips. At the gateway's ~500 QPS router ingest rate, ~5 messages accumulate per 10ms linger window, batched into a single broker request.
- `queue.buffering.max.messages=100000`: Prevents producer backpressure under burst traffic.

**Why Kafka over Celery + Redis:** Kafka provides durable, ordered, replayable event streams with built-in partitioning for future horizontal scaling. Celery would have been simpler for task dispatch but does not support replay, consumer-group rebalancing, or multi-service fan-out. The Kafka infrastructure also supports future event sourcing (pipeline.results, audit events).

---

## pgvector for Evidence Grounding Rather Than a Separate Vector Store

Storing embeddings in PostgreSQL via pgvector eliminates an external dependency (Pinecone, Weaviate, Chroma) and keeps all patient data co-located under a single data governance boundary — a meaningful property for HIPAA-friendly architecture.

**Performance trade-off:** pgvector with `IVFFlat` or `HNSW` indexes scales to millions of vectors with reasonable ANN performance. The practical constraint at clinic scale is concurrent query throughput, not total vector count. Migration to a dedicated vector store would be warranted at enterprise-scale concurrent session loads, not before.

**Note on HIPAA language:** The architecture is designed to be HIPAA-*friendly* (co-located PHI, audit trails, per-node trace logs, physician approval gate, field-level provenance). Actual HIPAA compliance requires deployment-specific configuration — BAA with cloud provider, encryption at rest and in transit, access controls, and audit logging. These are deployment requirements, not code requirements.

---

## `server/main.py` Instead of `server/app.py`

The FastAPI application was moved from `app.py` to `main.py` because the `server/app/` package directory shadows the `app` module name in Python's import resolution, causing an ASGI lookup failure at startup (`uvicorn app:app` would resolve to the package, not the module). The server is launched as `uvicorn main:app --reload --port 3001` from the `server/` directory.

---

## Synchronous Pipeline Execution via Kafka Consumer

The Python backend consumes `pipeline.trigger` messages via a Kafka consumer worker pool. Each consumed message invokes the full 16-node LangGraph pipeline synchronously within the consumer thread via `asyncio.run_in_executor`.

**Real-time progress:** `WorkflowEngine._stream_with_progress` iterates `graph.stream()` in the background thread, updating Redis after each node completes. The Go gateway exposes `GET /api/session/{id}/pipeline/status` which reads from Redis to drive the frontend progress sidebar (~500ms poll interval).

**Performance:** The reproducible harness and artifact location for end-to-end pipeline behavior are tracked in `docs/benchmarks/full-pipeline/`. The latest checked-in local evidence shows a warm single run at `16.38s` and a 10-VU median completed iteration duration of `42.08s`. The dominant cost center remains `extract_candidates`, which combines LLM inference with semantic grounding.

**Limitation:** Long-running OCR on large documents may approach timeout thresholds. SSE streaming via LangGraph's `astream_events` is planned as a lighter-weight alternative that preserves real-time progress without requiring additional infrastructure.
