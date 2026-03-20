# MedScribe — Engineering Decisions

## LangGraph with Checkpoint Persistence Over a Custom State Machine

LangGraph was selected over a hand-rolled pipeline because it provides native state serialisation, conditional edge routing, and interrupt/resume semantics. Each of the 18 nodes checkpoints `GraphState` to SQLite via `SqliteSaver`, keyed by `thread_id` (the `session_id`).

**AgentContext dependency injection:** Each node receives its services — `LLMClient`, `EmbeddingService`, `PatientRepository` — via an injected `AgentContext` dataclass rather than importing singletons. `make_node(fn, ctx)` wraps each node function and detects whether it accepts a second `ctx` parameter; nodes that do receive it, context-free nodes do not. This makes every node independently unit-testable.

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

**Interrupt/resume mechanism:** `build_graph()` accepts `enable_interrupts=True`, which compiles the graph with `interrupt_before=["human_review_gate"]`. When the graph reaches the node boundary before `human_review_gate`, it checkpoints state and pauses. To resume, `engine.resume(thread_id)` calls `graph.invoke(None, config={"configurable": {"thread_id": session_id}})` — passing `None` as state tells LangGraph to load from the checkpoint and continue.

**Current status:** The `/pipeline` endpoint currently calls `WorkflowEngine(enable_interrupts=False)`. The infrastructure is in place; enabling it requires changing one parameter and adding a resume endpoint.

---

## Groq Inference Over Local Model Serving

Whisper and pyannote-audio are present in `requirements.txt` but are disabled at startup due to a `torchvision::nms` DLL conflict introduced by the PyTorch/Lightning version intersection on Windows. Rather than blocking development on a package conflict, Groq's hosted llama-3.3-70b was adopted as the inference backend.

This produced an unexpected benefit: the server deploys on CPU-only machines with no CUDA dependency (`requirements.docker.txt` uses `torch==2.2.0+cpu`), significantly reducing the infrastructure footprint. SOAP note generation runs in approximately 1–3 seconds. Local Whisper inference remains on the roadmap.

LLM is invoked in four nodes: `diagnostic_reasoning`, `repair`, `field_extractor` (OCR disambiguation), and `generate_note`. All other reasoning — validation, clinical suggestions, conflict detection — is deterministic.

---

## Silero VAD Gating the Web Speech API

The Web Speech API alone misses the first 100–400ms of each utterance because the browser delays recognition start until audio crosses a noise threshold. Silero VAD (via `@ricky0123/vad-react`) runs in a Web Worker and fires `onSpeechStart` at approximately 50–100ms after voice onset, at which point the parent thread initialises the recognition session. An 800ms pre-speech audio pad is buffered so the recogniser has framing context for the full utterance.

This hybrid approach is specific to the browser prototype. Server-side Whisper will replace it once GPU resources are available.

---

## pgvector for Evidence Grounding Rather Than a Separate Vector Store

Storing embeddings in PostgreSQL via pgvector eliminates an external dependency (Pinecone, Weaviate, Chroma) and keeps all patient data co-located under a single data governance boundary — a meaningful property for HIPAA-friendly architecture.

**Performance trade-off:** pgvector with `IVFFlat` or `HNSW` indexes scales to millions of vectors with reasonable ANN performance. The practical constraint at clinic scale is concurrent query throughput, not total vector count. Migration to a dedicated vector store would be warranted at enterprise-scale concurrent session loads, not before.

**Note on HIPAA language:** The architecture is designed to be HIPAA-*friendly* (co-located PHI, audit trails, per-node trace logs, physician approval gate, field-level provenance). Actual HIPAA compliance requires deployment-specific configuration — BAA with cloud provider, encryption at rest and in transit, access controls, and audit logging. These are deployment requirements, not code requirements.

---

## `server/main.py` Instead of `server/app.py`

The FastAPI application was moved from `app.py` to `main.py` because the `server/app/` package directory shadows the `app` module name in Python's import resolution, causing an ASGI lookup failure at startup (`uvicorn app:app` would resolve to the package, not the module). The server is launched as `uvicorn main:app --reload --port 3001` from the `server/` directory.

---

## Synchronous Pipeline Execution via HTTP

The full LangGraph graph runs synchronously within a single POST response to `/api/session/{id}/pipeline`, executed via `asyncio.run_in_executor` to avoid blocking the event loop. This simplifies the client — no polling loop or WebSocket handshake is required — but caps request duration at the Uvicorn worker timeout.

**Real-time progress:** `WorkflowEngine._stream_with_progress` iterates `graph.stream()` in the background thread, updating `pipeline_progress_store` after each node. The frontend polls `GET /api/session/{id}/pipeline/status` (~500ms interval) to drive the progress sidebar with per-node status and duration.

**Limitation:** Long-running OCR on large documents may approach the 120-second axios timeout configured on the client. Moving the pipeline to a Celery + Redis task queue would decouple execution latency from the HTTP connection — the pipeline endpoint would return `202 Accepted` immediately and the frontend would poll for completion. A streaming SSE endpoint via LangGraph's `astream_events` is a lighter-weight alternative that preserves real-time progress without requiring a task queue.
