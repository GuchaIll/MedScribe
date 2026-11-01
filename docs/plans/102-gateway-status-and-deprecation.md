# 102 — Reconcile gateway pipeline status and deprecate legacy bridge routes

**Issue:** #102
**Parent issue:** none
**Sub-issues:** none
**Branch:** `fix/102-gateway-status-and-deprecation`
**Source docs:** `docs/design/ingestion-runtime-k8s.md` §2, defects D8–D10; `docs/copilot_runtime_contract.md`

## Goal

The gateway exposes a complete, truthful pipeline status by merging Python's
per-node progress with its top-level result. A Python pipeline result whose
declared status is failed is surfaced as failed at the gateway rather than
silently reported as completed.

## Scope

In scope:
- Merge the Redis top-level pipeline status with the Redis per-node progress
  record in the Go gateway read path.
- Treat a Python `status=failed` pipeline response as a terminal failure in the
  Go Kafka proxy.
- Add focused Go tests for both behaviors.
- Document legacy, duplicate, and stub API endpoints with their removal gates.

Out of scope:
- SessionService consolidation and transcript-source unification.
- Object storage intake, `ingest_documents`, `ingest_tasks`, and the outbox.
- Intent-gate execution, the shared-tool executor, and `/assistant` migration.
- Replacing the browser/Web Speech default path or configuring a speech provider.

## Steps

1. Extend `services/api/internal/usecase/pipeline.go` to decode and merge the
   Python-written `pipeline:progress:{session_id}` record into the gateway
   `PipelineStatus`, preserving the gateway-owned result fields.
2. Extend `services/api/internal/usecase/pipelineproxy/handler.go` so a valid
   Python body declaring failure updates the top-level status to `failed` and
   returns an error to the consumer.
3. Add regression tests for progress merge, malformed progress fallback, and a
   declared Python failure.
4. Add an API migration/deprecation inventory in `docs/` that names current
   ownership, endpoint status, and removal preconditions without removing any
   externally callable endpoint in this issue.

## Test criteria

Commands:
- `go test ./internal/usecase/...` passes
- `go test ./internal/controller/http/...` passes

Acceptance (copied from the issue, one line each):
- [ ] Gateway status responses include node progress when Python has written it.
- [ ] A Python failed JSON response leaves the top-level pipeline status failed, not completed.
- [ ] Tests cover status merge and failed response handling.
- [ ] API deprecation inventory names legacy/stub routes and removal gates.

## Risks and open questions

- Python progress timestamps are ISO-8601 while the Go public type currently
  uses milliseconds. Preserve node fields as returned where possible and make
  absence or malformed progress non-fatal.
- Kafka delivery semantics for an application-declared failure must remain
  visible to the consumer; returning an error can retry the message, so the
  terminal Redis state must be written before returning.
- The inventory labels endpoints only. Removal requires a separate issue after
  the intent-gated assist runtime and durable ingestion replacements exist.
