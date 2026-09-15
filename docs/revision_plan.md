# MedScribe Revision Plan

This plan maps the **current implementation** to the **target architecture**
described in [architecture.md](./architecture.md). It is intentionally
priority-based: each phase protects a user-facing guarantee before adding more
distributed complexity.

## Priority Order

1. **Protect transcript capture first**
   If every downstream worker stalls, the encounter must still keep recording
   speech reliably.
2. **Move expensive work off the request path**
   OCR, note generation, and record enrichment can complete later.
3. **Only split services at coarse boundaries**
   The first service cuts should isolate failure domains, not turn every graph
   node into an RPC.

## Current State Summary

- The Go gateway validates and accepts transcript turns, but does not durably
  store them yet.
- Pipeline execution is decoupled through Kafka. The Go service is built as a
  single image that runs in modes (`--mode=gateway|pipeline-worker|ocr-worker|
  audio-worker|all`): in production the gateway (HTTP only) and the three Kafka
  consumer proxies run as separate Kubernetes Deployments off that one image
  (see `infra/k8s/`); locally, `--mode=all` runs them in one process. The
  gateway no longer hosts the consumers in-process except in `all` mode.
- OCR upload through the Go gateway is still stubbed.
- Active session state mostly lives in Python process memory, not Redis.
- Session end closes the encounter, but does not yet flush all hot-path data
  through a durable non-Python path.

## Phase 1: Protected Transcription Hot Path

**Status**

Started in the Go gateway:

- transcript turns are buffered in Redis on ingest
- closed sessions reject new turns
- session end flushes buffered turns into durable session metadata

**Goal**

Make `POST /session/{id}/transcribe` reliably capture utterances without
waiting on OCR, LangGraph, note generation, RAG, or physician review.

**Why this comes first**

This is the most important clinical reliability guarantee. If transcript turns
can be lost, every downstream architecture decision is secondary.

**Scope**

- Append transcript turns to Redis immediately
- Keep the request/response path lightweight
- Flush buffered transcript turns on `POST /session/{id}/end`
- Preserve the existing Python stack until a dedicated transcript persister is
  introduced

**Acceptance criteria**

- A slow or failing pipeline worker does not block transcript ingestion
- Transcript turns are recoverable from Redis during an active session
- Session end persists buffered transcript state into durable session metadata
- Closed sessions reject new transcription writes

## Phase 2: Async OCR Ingress And Pending Review Lane

**Status**

Implemented in the Go gateway:

- upload captures the original file into staging storage
- OCR jobs are published asynchronously
- pending uploads and OCR job state are mirrored into Redis session state
- `GetDocuments` can surface pending uploads before OCR completes

**Goal**

Turn document upload into a non-blocking ingress path that captures the file,
queues OCR work, and exposes pending uploads immediately.

**Why this is second**

OCR is among the heaviest and least predictable workloads in the system. It
must not compete with transcript capture on the hot path.

**Scope**

- Accept upload through the Go gateway
- Spool the original file to local/object-backed staging storage
- Enqueue OCR work asynchronously
- Expose queued uploads as pending session documents
- Keep physician sign-off as the gate before record mutation

**Acceptance criteria**

- Upload returns quickly after file capture and job enqueue
- OCR work can lag without affecting transcription
- Pending uploads are visible before the OCR worker finishes
- No automatic patient-record mutation happens at upload time

## Phase 3: Redis Session View + Coarse-Grained Workers

**Status**

Foundation started:

- active session snapshots now live in Redis
- pipeline trigger refreshes patient/session metadata in that snapshot
- assistant queries can answer from Redis session context plus structured DB reads

Still pending:

- dedicated note worker and summary/discharge job lane
- review/persistence worker — **Python staging side done**: when a run needs
  physician review, `persist_results` no longer mutates the patient record; it
  stages the proposed record + discrepancies in the Redis `pipeline:review:{id}`
  key (`core/review_queue.py`) for end-of-session sign-off. The Go review API
  (`GET /session/{id}/review`, `POST /session/{id}/review/signoff`) and the
  worker that commits approved changes on sign-off are the remaining work.
- dedicated transcript persister
- moving the Python in-memory session model behind the Redis-backed encounter view

**Goal**

Move the rest of the active encounter workflow to the target production shape:
Redis-backed encounter memory with coarse worker lanes.

**Scope**

- Move active encounter view out of Python process memory and into Redis
- Split workers by responsibility:
  - `pipeline-worker`
  - `ocr-worker`
  - `note-worker`
  - `assistant/query-worker`
  - `review-persist-worker`
- Build session summary, discharge, and SOAP generation from Redis first, then
  optional DB/RAG retrieval
- Treat session end as a full durability flush boundary

**Acceptance criteria**

- Assistant queries can answer from Redis, DB/tool lookup, or RAG as needed
- Notes and summaries are background jobs, not blocking request handlers
- Approved OCR or pipeline-derived field changes are persisted only after
  physician sign-off
- End-session flush persists transcript, approved changes, and finalized notes

## Architecture Tradeoffs

### What to split now

- Gateway / ingress
- OCR worker
- Pipeline worker
- Note generation worker
- Review/persistence worker

### What not to split yet

- Individual OCR stages
- Individual LangGraph nodes
- Fine-grained RAG/tool/database services for a single request path

### Why

Coarse boundaries isolate slow workloads without paying unnecessary network,
serialization, and coordination overhead. Fine-grained service splits would
likely hurt performance before they help.

## Suggested Execution Order

1. Ship Phase 1 and verify transcript durability under worker slowdown.
2. Ship Phase 2 and verify multi-page document uploads no longer affect live
   encounter responsiveness.
3. Move active session read/write paths to Redis in Phase 3.
4. Extract the pipeline proxy out of the gateway process after Redis-backed
   encounter state is in place.
