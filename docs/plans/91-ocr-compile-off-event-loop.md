# 91 — OCR off the event loop, compile to its own process (T0 triage)

**Issue:** #91
**Parent issue:** #77 (agent refactor epic)
**Sub-issues:** none
**Branch:** `fix/91-ocr-compile-off-event-loop`
**Source docs:** `docs/design/medscribe-runtime-sdd.md` §2.3.3 T0, §9.3 step 1, defects D1 and D9, §5.2.8.1 (workload placement). These SDD docs are untracked local files in the main checkout (`/Users/guchaill/Coding/MedScribe/docs/design/`), not in git.

## Goal

An upload or a compile in one session no longer stalls requests in other
sessions. OCR and Lane B compile run in child processes owned by the API
process. The paired probe shows `/transcribe` p99 and `/assistant` p95 are about
the same idle and while an 8-page PDF ingests.

This is a stopgap. T5 (#59) moves OCR into the `ingest-page` worker and T15
(#61) moves compile into `compile-worker`, both separate deployments. Keep this
change small and easy to delete later.

## Prerequisites (check before writing code)

1. **Alembic has two heads on `main`.** `004_provenance_receipt_locators` and
   `005_agent_trace_spans` both have `down_revision = "003_nullable_session_patient"`.
   `server/Dockerfile` runs `alembic upgrade head` at startup, which fails with
   two heads, so the compose `api` container will not start. The probe needs a
   running API. Fix it first in its own small PR (`fix/alembic-two-heads`):
   either set `005.down_revision = "004_provenance_receipt_locators"` (005 only
   creates `agent_trace_spans`, so it does not depend on 004's columns), or add
   an empty merge revision. Check that `alembic heads` prints one head. Do not
   fold this into the #91 branch.
2. **The local venv is missing deps.** `/Users/guchaill/Coding/MedScribe/.venv`
   has no `sqlalchemy`, so 36 test modules fail to collect on `main`. Run
   `.venv/bin/pip install -r server/requirements.txt` before testing. Run
   pytest with `-o addopts=""`, because `pytest.ini` adds `--cov` flags that need
   `pytest-cov`.
3. Read `AGENTS.md` (issue workflow, implementation rules, data-model proof).
   The PR body needs Changes / Plan / Test criteria / Self-review.

## Current behavior (verified 2026-10-20)

**OCR (D1).** `POST /api/session/{session_id}/upload`
(`server/app/api/routes/session.py::upload_documents`, about line 409) awaits
`app.core.ocr.pipeline.process_document`. That function is `async def` but
awaits nothing. It calls `split_document`, `_process_single_page` (RapidOCR via
ONNX Runtime, preprocessing, layout detection), `classify_document`,
`extract_fields` and `detect_conflicts` synchronously, and the Groq client calls
in `document_classifier.py` / `field_extractor.py` are synchronous HTTP. So one
upload blocks the event loop for the whole document, and every other request in
that uvicorn worker waits. The Go `ocr-worker`
(`services/api/internal/usecase/ocrproxy/handler.go`) POSTs into this same route,
so Kafka-queued uploads stall the API the same way (D4 is out of scope here).

**Compile (D9).** `POST /api/session/{session_id}/pipeline` (`session.py`, about
line 78) and `POST /internal/pipeline`
(`server/app/api/routes/internal_pipeline.py::run_pipeline_internal`) build a
`WorkflowEngine(db_session=db)` and await `engine.execute_async(state)`.
`execute_async` (`server/app/core/workflow_engine.py`, about line 136) runs
`_stream_with_progress` via `loop.run_in_executor(None, ...)`, a thread in the
API process. The loop is not blocked outright, but CPU-heavy nodes hold the GIL
and starve the loop, and the 16-node graph shares the API's memory and DB pool.

**State that matters for process separation:**
- `SessionService` (`server/app/services/session_service.py`) keeps session state
  in `self._store`, an in-process dict. A child process cannot write to it.
  **Therefore the child functions must be pure: data in, result out. The parent
  writes all session state.**
- `PipelineProgressStore` (`server/app/core/pipeline_progress.py`) is
  Redis-backed with an in-memory fallback. From a child, progress reaches the
  status endpoint only through Redis.
- The graph has no checkpointer (`server/app/agents/graph.py` about line 180:
  Redis checkpointing disabled), so no in-process checkpoint state is lost.
- RapidOCR is a lazy module-level singleton (`server/app/core/ocr/extractor.py`
  `_rapid_ocr_instance`). Each child process builds its own once.
- `persist_results.py` (about line 436) schedules post-processing with
  `loop.create_task` when a loop is running, else runs it synchronously. In the
  child there is no running loop, so it runs synchronously inside the job.
  Confirm this, and confirm nothing depends on it running after the response.

## Design

### New module `server/app/core/offload.py`

One place that owns the child processes, so T5/T15 can delete it in one go.

- Two `concurrent.futures.ProcessPoolExecutor`s with
  `mp_context=multiprocessing.get_context("spawn")`. Use spawn, not fork: fork
  copies the parent's open DB connections, Redis clients, and threads into the
  child.
  - `ocr` pool: `OCR_POOL_WORKERS`, default 1.
  - `compile` pool: `COMPILE_POOL_WORKERS`, default 1.
  - Read both from settings (`server/app/config` or `config.yaml`, matching the
    existing config loader). Validate them as ints in `[1, 8]`; anything else
    raises a config error naming the variable and the value.
- Created in the FastAPI lifespan startup in `server/main.py` and shut down on
  shutdown (`shutdown(wait=False, cancel_futures=True)`). With
  `uvicorn --workers N`, each worker owns its own pools. Note that in the plan
  and the README, because total processes = N x (1 + ocr + compile).
- `initializer` for the OCR pool warms the RapidOCR singleton, so the first job
  does not pay model load. The compile pool initializer configures logging only.
- Public API:
  - `async def run_ocr(job: OcrJob) -> OcrJobResult`
  - `async def run_compile(job: CompileJob) -> CompileJobResult`
  - Both: submit to the pool via `loop.run_in_executor(pool, fn, job)`, apply a
    timeout (`OCR_JOB_TIMEOUT_S` default 300, `COMPILE_JOB_TIMEOUT_S` default
    600), log entry/exit with `session_id`, `doc_id` (OCR), job id, queue wait
    ms, run ms, and mode.

### Child entry points (module-level functions, picklable)

- `_ocr_child(job) -> OcrJobResult`: `asyncio.run(process_document(...))` with
  the job's fields. It returns the `DocumentProcessingResult` fields the route
  reads. Before relying on pickling, check that every field on
  `DocumentProcessingResult`, `ExtractedField`, `ConflictItem`,
  `DocumentClassification` and `PageProcessingResult` pickles (dataclasses
  and enums pickle; images or numpy arrays held on `pages` may be large, so drop
  page images from the returned object if present).
- `_compile_child(job) -> CompileJobResult`: opens its own
  `SessionLocal()` (from `app.database.session`), builds
  `WorkflowEngine(enable_checkpointing=True, enable_interrupts=False, db_session=db)`
  (cached per child process for the graph build, with a new DB session per
  job), runs `engine._stream_with_progress(state, config, session_id)` directly
  (it is sync), and closes the DB session in `finally`. It returns only the
  fields the routes read: `clinical_note`, `structured_record`,
  `clinical_suggestions`, `validation_report`, `message`, plus
  `flags.processing_error`.
- The request's DB session never crosses the process boundary.

### Job and result models (data-model proof required)

Do not create a new state model. Reuse what exists:
- `OcrJob` = the keyword arguments `process_document` already takes
  (`file_path`, `session_id`, `patient_id`, `patient_history`,
  `original_filename`). Pass them as a frozen dataclass so the pool call is
  typed. Each field is read by `_ocr_child` to call `process_document`. No other
  fields.
- `OcrJobResult` = `DocumentProcessingResult` itself (reuse, do not copy).
- `CompileJob` = `{"state": GraphState, "thread_id": str}`. `GraphState` is the
  existing type. `CompileJobResult` = the existing `GraphState` subset the
  routes already read. If you need a dataclass, name only the fields the
  response models (`RunPipelineResponse`, `InternalPipelineResponse`) read.
- Put a per-field consumer table in the PR Self-review (AGENTS.md data-model rule).

### Route changes

- `upload_documents`: replace `await process_document(...)` with
  `await offload.run_ocr(OcrJob(...))`. Everything after it (queue items,
  `service.add_to_queue`, `service.add_document`, field changes) stays in the
  parent unchanged.
- `WorkflowEngine.execute_async`: replace `loop.run_in_executor(None, ...)` with
  `await offload.run_compile(CompileJob(...))`. Keep progress init in the parent
  (`pipeline_progress_store.init_pipeline`), keep the error path the same. Both
  compile routes then get process isolation without route edits.
  `create_initial_state` stays in the parent, because it reads stored documents
  from the in-memory session store.

### Failure and fallback behavior (must be explicit, logged, visible)

| Case | Behavior |
| --- | --- |
| Pool not started (startup failed, or a test without lifespan) | Raise `OffloadUnavailableError`, a new project error naming the pool and the startup error. The upload or compile returns 503 for that file or session. **No silent inline run.** |
| `BrokenProcessPool` (child died: OOM, segfault in ONNX) | Log at `error` with pool name, job id, session id, doc id. Recreate the pool once and retry the job once. If the retry also breaks, fall back to `asyncio.to_thread` for that job, log at `warning` with `mode=thread_fallback`, increment `offload_fallback_total{pool}`, and set response header `X-MedScribe-Offload: thread_fallback`. The probe script reads that header, and the fallback is visible to the caller. Do not fall back to running on the loop itself. |
| Job timeout | Log at `error`. The upload returns that file's entry with `status = "failed"`, `error = "ocr_timeout"` (match the existing per-file error shape in `upload_documents`). Compile marks `pipeline_progress_store.mark_pipeline_failed` and returns 504. The child keeps running until it finishes. A process pool cannot cancel a running job, so a hung child holds one slot. Record this as a known limit. |
| Exception inside the child | Re-raised in the parent by the executor. Handle exactly as today (existing try/except per file in `upload_documents`, existing error path in `execute_async`). Log with job id. |
| Unpicklable argument or result | A test catches it before merge (see tests). At runtime it surfaces as a `PicklingError`. Log at `error` and fail that job. |
| Redis unavailable while compile runs in a child | Progress written to the child's in-memory fallback is invisible to the status endpoint. Log at `warning` once per job from the child: "progress store has no Redis; status endpoint will not see child progress". Do not try to proxy progress through a pipe in T0. |
| Empty upload list / zero-byte file | Unchanged from today; validate before submitting a job (no job for a zero-byte file; return that file as failed with `error = "empty_file"`). |
| Duplicate upload of the same file | Unchanged (T4 #93 owns idempotent intake). |

Logging rules (AGENTS.md): log ids, counts, sizes, durations. Never log
transcript text, document text, extracted values, or the Groq key.

## As built (updated during implementation)

Changes from the design above, and why:

- **Prerequisite 1 (Alembic heads)** is handled by PR #99 (`fix/alembic-two-heads`,
  005 revises 004). Not folded in here. The probe ran with
  `alembic upgrade heads` so it did not depend on #99.
- **Prerequisite 2 (venv).** The main `.venv` is Python 3.14, and `torch==2.2.0`
  and `numpy==1.26.4` have no 3.14 wheels. Tests ran in a Python 3.12 venv built
  from `requirements.docker.txt` minus torch/sentence-transformers/weasyprint,
  with `pydantic` relaxed to `>=2.7` (`langchain-core==0.2.43` needs it; the
  Docker pin `pydantic==2.5.3` conflicts) plus `pdfplumber`. `pdfplumber` is
  also missing from `requirements.docker.txt`, so in Docker every PDF goes
  through the image path (poppler + RapidOCR). Not changed here.
- **`CompileJob` has five fields, not two.** The child rebuilds the caller's
  `WorkflowEngine`, so it needs the caller's `enable_checkpointing` and
  `enable_interrupts` (the two compile routes differ), and `use_db` because the
  request's DB session cannot cross the process boundary. No engine is cached in
  the child: `create_default_context(db_session=...)` binds the session at build
  time, so a cached engine would hold a stale session.
- **`execute_async` returns `state` merged with `offload.COMPILE_RESULT_KEYS`**
  (`clinical_note`, `structured_record`, `clinical_suggestions`,
  `validation_report`, `message`, `flags`), not the full child state. Every
  caller reads only these keys.
- **The post-OCR summary LLM call moved off the loop too.**
  `_build_document_agent_summary` calls `LLMClient.generate_response`
  synchronously after OCR. Left in place it would still stall the loop for one
  Groq round trip per file. It now runs in `asyncio.to_thread` (I/O-bound, so a
  thread is enough).
- **Upload checks the OCR pool once, up front.** If the pool is down the whole
  request returns 503 before any file is stored. Per-file failures keep the
  existing per-file shape (`error` key only, no new `status` key):
  `error = "ocr_timeout"` and `error = "empty_file"`.
- **`/internal/pipeline` keeps its contract with the Go proxy:** any failure,
  including 503/504 causes, still returns 200 with `status = "failed"`. The
  public `/api/session/{id}/pipeline` returns 503 / 504. Both set
  `X-MedScribe-Offload` on success.
- **Uploaded filenames are no longer logged** (they can carry patient names);
  logs use the stored uuid name as `doc_id`.
- **Step 10 (k8s) does not apply as written.** `infra/k8s/services/api` is the
  Go gateway (`--mode=gateway`, 512Mi limit). The Python API is reached at
  `python-backend:3001` and has no manifest in `infra/k8s`. Added a note to
  `infra/k8s/README.md` with the process count and measured child RSS instead.
- **Thread fallback also enforces the job timeout.**
- **Found by the probe: every spawn child died at import.** `server/main.py`
  inserted `server/app` at `sys.path[0]`. Spawn children inherit `sys.path`,
  and in a fresh interpreter `server/app/logging.py` shadows the stdlib
  `logging` (`'logging' is not a package`). The pool broke on every job, and the
  fallback ran OCR in a thread, as designed and visibly
  (`X-MedScribe-Offload: thread_fallback`), which still stalled the loop. Unit
  tests missed it because they never import `main.py`. Nothing imports from
  `server/app` by bare name, so the insert is removed. Regression test:
  `test_child_starts_from_process_that_imported_main`.
- **Found by the probe: `/assistant` blocked the loop itself.** The route is
  `async def` but calls the sync `AssistantService.ask_question` (embedding +
  LLM) inline. Under CPU contention from OCR each call grew past 1 s, and at
  1 rps open-loop the loop never drained, so every session queued behind it
  (measured: `GET /` waited up to 7 s, `/assistant` 0.8 s -> 27 s). With
  `/assistant` excluded, nothing stalled during an upload. It now runs in
  `asyncio.to_thread`. `get_embedding_service(db)` still runs on the loop; its
  first call loads the model (about 15 s, once per process). The probe warms it
  first. Left for a follow-up.
- **Found by the probe: CPU oversubscription.** ONNX Runtime sizes its
  intra-op pool to every visible core (12 in the probe container) and ignores
  the 4-CPU quota. The OCR child ran 48 threads next to the parent's torch
  threads. New setting `OCR_CHILD_THREADS` (default 2, range 1-16) caps it via
  `RapidOCR(intra_op_num_threads=..., inter_op_num_threads=1)`, set in the OCR
  child initializer before the singleton is built. It also halved OCR time
  (117 s -> 51 s for 8 pages).
- **Exit criterion not met: 1.48x (`/transcribe` p99) and 1.30x (`/assistant`
  p95) against 1.2x,** down from 204x / 205x on `main`. Details in
  `docs/benchmarks/t0-isolation/README.md`. The threshold was not loosened.
- **API process INFO logs were dropped.** `app.logging.configure_logging` was
  never called, so only the last-resort WARNING handler was active and the
  offload job logs (`session_id`, `doc_id`, `queue_wait_ms`, `run_ms`) never
  appeared. The lifespan now calls it (console, `settings.logging.level`), and
  the child initializer uses the same function. Visible change: `app.*` INFO
  logs now print in the API process. `medscribe.startup` sets
  `propagate = False` so its lines do not print twice.

### Data-model proof (per field)

| Model | Field | Read by | Interface crossed |
| --- | --- | --- | --- |
| `OcrJob` | `file_path`, `session_id`, `patient_id`, `patient_history`, `original_filename` | `_ocr_child` -> `process_document(**)` | parent -> OCR child (pickle) |
| `CompileJob` | `state` | `_compile_child` -> `_stream_with_progress` | parent -> compile child |
| | `thread_id` | `_compile_child` -> `_get_config` | parent -> compile child |
| | `enable_checkpointing`, `enable_interrupts` | `_compile_child` -> `WorkflowEngine(...)` | parent -> compile child |
| | `use_db` | `_compile_child` (opens `SessionLocal()` or not) | parent -> compile child |
| `OffloadResult` | `value` | `upload_documents`, `execute_async` | offload -> route |
| | `mode` | routes -> `X-MedScribe-Offload` header | offload -> HTTP caller |
| `OffloadConfig` | `ocr_pool_workers`, `compile_pool_workers`, `ocr_job_timeout_s`, `compile_job_timeout_s` | `offload.start` -> `_Pool` | config -> lifespan |
| | `ocr_child_threads` | `_init_child` -> `extractor.set_rapid_ocr_threads` | config -> OCR child |

OCR result reuses `DocumentProcessingResult` unchanged (`pages` emptied before
it crosses the pipe; no route reads it). Compile result reuses the `GraphState`
key names. No new state model.

## Steps

1. (Separate PR, prerequisite) Fix the Alembic two-heads problem; confirm `docker compose up api` starts.
2. Commit this plan as the first commit on `fix/91-ocr-compile-off-event-loop`.
3. Add settings `OCR_POOL_WORKERS`, `COMPILE_POOL_WORKERS`, `OCR_JOB_TIMEOUT_S`, `COMPILE_JOB_TIMEOUT_S` with validation.
4. Add `server/app/core/offload.py` (pools, lifespan hooks, `run_ocr`, `run_compile`, error type, fallback, metrics). Use `prometheus_client` the way `server/app/agents/tracing/sinks.py` does: optional import, no-op if missing.
5. Wire the lifespan in `server/main.py`.
6. Swap the call in `upload_documents`.
7. Swap the executor in `WorkflowEngine.execute_async`; add `_compile_child`.
8. Write the unit tests (below).
9. Write `scripts/probe_isolation.py` (or `.js` with k6 if you prefer; `scripts/qps_bench.js` already uses k6). Run the paired probe (below) and commit the report to `docs/benchmarks/t0-isolation/`.
10. Update `infra/k8s/services/api/deployment.yaml` resource requests and limits to cover the child processes (memory: each OCR child loads ONNX models, about 300-500 MB; measure it), and note the process count in `infra/k8s/README.md`.
11. Self-review against AGENTS.md, then push and open the PR.

## Tests

Unit (`server/tests/unit/test_offload.py`):
- The event loop stays responsive while an OCR job runs. Submit a fake CPU-bound child (busy loop for 2 s) and, concurrently, `await asyncio.sleep(0.01)` 100 times. Assert the max sleep overshoot is < 50 ms. Run the same test against the old inline path to show it fails there (or document the before number).
- `OcrJob` and a real `DocumentProcessingResult` round-trip through `pickle`.
- A `GraphState` from `WorkflowEngine.create_initial_state` round-trips through `pickle` (catches live objects in state).
- Pool not started -> `OffloadUnavailableError`, and the route returns 503.
- Child raises -> the exception reaches the parent and is handled by the existing per-file error path.
- `BrokenProcessPool` -> one recreate and retry, then thread fallback with a warning log, the metric incremented, and the header set (simulate by killing the child with `os._exit(1)`).
- Timeout -> file entry `failed` / `ocr_timeout`; compile 504 and progress marked failed.
- Config validation: `OCR_POOL_WORKERS=0`, `"abc"`, `9` each raise a config error naming the variable.

Integration (requires compose `db` + `redis`, marker `integration`):
- Upload `server/tests/ocr_examples/discarhege_text_test.pdf` end to end; the response shape is unchanged from `main` (snapshot the keys).
- Run `/pipeline` with seeded segments; the response shape is unchanged; the status endpoint shows node progress (Redis path).

## Paired latency probe (the exit criterion)

- Setup: `docker compose up -d db redis api` (plus `speech-worker` if `/transcribe` calls it; check `session.py::transcribe_audio`). One uvicorn worker, so the stall is not hidden by a second worker.
- Load: two concurrent "other session" clients. Client A posts `/api/session/{a}/transcribe` with a fixed small audio chunk at 2 rps. Client B posts `/api/session/{b}/assistant` with a fixed question at 1 rps. 60 s per phase.
- Phase 1 (idle): only A and B.
- Phase 2 (ingesting): A and B, plus session C uploads an 8-page PDF (build one by concatenating fixture pages; commit the generator script, not PHI).
- Optional phase 3: A and B plus one `/pipeline` compile on session C.
- Report `/transcribe` p50/p99 and `/assistant` p50/p95 per phase, error counts, and the `X-MedScribe-Offload` header values seen. Run the same probe on `main` first and commit both numbers. The before/after is the evidence.
- "No material difference" means: p99 `/transcribe` ingesting <= 1.2x idle, p95 `/assistant` ingesting <= 1.2x idle. State the thresholds in the report. If they are not met, say so in the PR. Do not loosen them.
- Note: `/assistant` may call an LLM. Use the same model and question in all phases, and report its variance in the idle phase so the threshold is meaningful.

## Acceptance (from the issue)

- [ ] OCR runs in a separate process, never inline in a request coroutine
- [ ] Lane B compile runs in its own process
- [ ] Paired probe: `/transcribe` p99 and `/assistant` p95, idle vs 8-page PDF ingesting, before and after
- [ ] Each offloaded job logged with `session_id`, `doc_id`, duration; every fallback logged at `warning`
- [ ] Exit: no material difference between idle and ingesting

## Out of scope

- The Go `ocr-worker` posting back into Python (D4) -> T2/T5 (#92, #59).
- Moving session state out of process memory (D5) -> #65.
- Real worker deployments for OCR and compile -> #59, #61, #96.
- Parallelizing pages within one document (the comment in `pipeline.py` line 71). Not needed for isolation, and #59 owns page parallelism.

## Risks and open questions

- **Memory.** Each OCR child holds ONNX models. Measure RSS per child and set pod limits from the measurement, not a guess.
- **Hung child holds a slot.** A process pool cannot cancel a running job. With `OCR_POOL_WORKERS=1`, one hung OCR job blocks all OCR for that API worker until it finishes. Acceptable for T0. If it shows up in the probe, use a per-job `multiprocessing.Process` with `terminate()` on timeout instead of a pool.
- **Groq rate limits.** Moving OCR off the loop does not change how many Groq calls run, but more uploads can now be in flight at once. Watch for 429s in the probe logs.
- **`--reload` in compose.** Uvicorn reload with spawn children: make sure children exit on reload (lifespan shutdown). Check for orphaned processes after a reload.
