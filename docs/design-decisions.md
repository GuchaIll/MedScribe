# MedScribe — Engineering Decisions

## LangGraph for Clinical Orchestration Over a Custom State Machine

LangGraph was selected over a hand-rolled pipeline because it provides native state serialisation, conditional edge routing, and interrupt/resume semantics. The 15-node pipeline runs on the Python backend, triggered by Kafka messages from the Go gateway.

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

## Groq Inference Over Local Model Serving

Whisper and pyannote-audio are present in `requirements.txt` but are disabled at startup due to a `torchvision::nms` DLL conflict introduced by the PyTorch/Lightning version intersection on Windows. Rather than blocking development on a package conflict, Groq's hosted Llama 4 Scout 17B (llama-4-scout-17b-16e-instruct) was adopted as the inference backend. This switch reduced end-to-end pipeline latency from 260s to 23.5s (11x improvement over the prior llama-3.3-70b configuration).

This produced an unexpected benefit: the server deploys on CPU-only machines with no CUDA dependency (`requirements.docker.txt` uses `torch==2.2.0+cpu`), significantly reducing the infrastructure footprint. SOAP note generation runs in approximately 1-3 seconds. Local Whisper inference remains on the roadmap.

LLM is invoked in four nodes: `diagnostic_reasoning`, `repair`, `field_extractor` (OCR disambiguation), and `generate_note`. All other reasoning -- validation, clinical suggestions, conflict detection -- is deterministic.

---

## Silero VAD Gating the Web Speech API

The Web Speech API alone misses the first 100–400ms of each utterance because the browser delays recognition start until audio crosses a noise threshold. Silero VAD (via `@ricky0123/vad-react`) runs in a Web Worker and fires `onSpeechStart` at approximately 50–100ms after voice onset, at which point the parent thread initialises the recognition session. An 800ms pre-speech audio pad is buffered so the recogniser has framing context for the full utterance.

This hybrid approach is specific to the browser prototype. Server-side Whisper will replace it once GPU resources are available.

---

## Go API Gateway with Strangler-Fig Migration

The monolithic Python FastAPI server was decomposed using a strangler-fig pattern. A Go API gateway (`services/api/`) now owns:

- **Authentication**: JWT-based registration and login via golang-jwt/v5
- **Session management**: CRUD operations with pgx/v5 connection pooling (50/50 min/max connections)
- **Request routing**: chi v5 mux with middleware chaining (JWT validation, Prometheus metrics, structured logging via zap)
- **Pipeline triggering**: Kafka publish with async return
- **Pipeline status**: Redis reads for real-time progress polling

Remaining endpoints (OCR, clinical reasoning, record generation, LLM provider management) are reverse-proxied to the Python backend. The gateway is the single entry point for all client traffic on port 8080.

**Why Go over extending Python:** The pipeline trigger endpoint is the highest-throughput path (targeting 500 QPS). Go's goroutine model, static compilation, and minimal GC pause times make it better suited for a high-concurrency request router than Python's asyncio. The Python backend remains optimal for LangGraph orchestration and ML workloads.

**In-process session cache:** A `sync.Map`-based TTL cache (`pkg/cache/cache.go`) with 1-hour expiry eliminates PostgreSQL round-trips on the hot path. On cache miss, the gateway queries PG and populates the cache. A background reaper goroutine evicts expired entries every 30 minutes. This reduced p50 trigger latency from ~15ms to < 1ms.

---

## Kafka Event Bus Over Synchronous HTTP Pipeline Trigger

Pipeline execution is decoupled from the HTTP request cycle via Apache Kafka 4.2 (KRaft mode, no ZooKeeper). When the gateway receives a pipeline trigger request:

1. Validates session (cache -> PG fallback)
2. Seeds pipeline status in Redis via async goroutine (fire-and-forget)
3. Produces a message to `pipeline.trigger` topic and returns `202 Accepted`

**Producer configuration rationale:**
- `acks=1` (leader acknowledgement only): Acceptable for pipeline triggers because the trigger is idempotent and the single-broker Docker setup makes `acks=all` equivalent to `acks=1` anyway. Eliminates fsync blocking on the hot path.
- Async delivery (`nil` delivery channel): Delivery reports are consumed by a background `drainEvents()` goroutine that logs failures via `fmt.Printf`. The gateway does not block on broker acknowledgement.
- Micro-batching (`linger.ms=10`, `batch.size=64KB`): Amortises broker round-trips. At 500 QPS, ~5 messages accumulate per 10ms linger window, batched into a single broker request.
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

The Python backend consumes `pipeline.trigger` messages via a Kafka consumer worker pool. Each consumed message invokes the full 15-node LangGraph pipeline synchronously within the consumer thread via `asyncio.run_in_executor`.

**Real-time progress:** `WorkflowEngine._stream_with_progress` iterates `graph.stream()` in the background thread, updating Redis after each node completes. The Go gateway exposes `GET /api/session/{id}/pipeline/status` which reads from Redis to drive the frontend progress sidebar (~500ms poll interval).

**Performance:** End-to-end pipeline latency is approximately 23.5 seconds (down from 260s after LLM model switch and node merging). The `extract_candidates` node accounts for ~50% of pipeline time due to LLM inference + semantic grounding.

**Limitation:** Long-running OCR on large documents may approach timeout thresholds. SSE streaming via LangGraph's `astream_events` is planned as a lighter-weight alternative that preserves real-time progress without requiring additional infrastructure.
