# API migration and deprecation status

**Status:** active migration inventory. This document is the source for route
deprecation decisions until the public API has one owner.

## Ownership rule

The Go gateway is the only supported public ingress. FastAPI is an internal
bridge for the current Python LangGraph compile and OCR implementations. A
route implemented in FastAPI is not therefore a supported public endpoint.

New clients must use the gateway route only. Existing direct FastAPI callers
must migrate before a route is removed. Internal routes must remain unreachable
from public ingress.

## How to read the inventory

This is a source audit, not production traffic telemetry. **Repository caller**
means a current source caller was found in `client/medscribe` (legacy) or
`client/v2` (new client). **Supported** means a new client may depend on the
route; it does not mean a second implementation with the same URL is valid.
Routes not marked supported are either compatibility routes or migration debt.

## Gateway routes

| Route | Status | Action and removal gate |
| --- | --- | --- |
| `POST /api/session/{id}/pipeline` and `GET /api/session/{id}/pipeline/status` | supported bridge | Keep until the compile-worker replaces the Python internal pipeline bridge. The status endpoint now merges gateway terminal state with Python node progress. |
| `POST /api/session/start`, `/{id}/end`, `/{id}/transcribe`, `/{id}/upload`, `/{id}/audio-segment` | supported migration ingress | Keep. Repository callers exist for start, transcribe, upload, and audio segment. Upload and audio bytes still use a pod-local spool and need object-storage intake before split-pod deployment. |
| `POST /api/session/{id}/speaker-role-check` | feature-flagged compatibility | Legacy-client caller. Keep while server-side diarization is optional; reassess after the real speech provider is the default. |
| `GET /api/session/{id}/record` and `GET /api/session/{id}/live-transcript` | supported migration read | Repository callers exist. Keep until the durable transcript and draft/record read models replace Redis/session-state reads. |
| `GET /api/session/{id}/documents`, `GET /api/session/{id}/queue`, `PATCH /api/session/{id}/queue/{item}` | compatibility-only | No new caller. Retire once SessionService migration removes queue/document state. |
| `POST /api/session/{id}/assistant` | replacement required, not removable yet | Legacy-client caller. The Go keyword answerer is an earlier prototype. Replace it with an intent-gated assist-runtime proxy before deprecation/removal. |
| `GET /api/patient/{id}/profile` | supported migration read | Legacy-client caller; retain while the profile response is the selected canonical contract. |
| `GET /api/patient/{id}/lab-trends` and `GET /api/patient/{id}/risk-score` | compatibility-only | No repository caller found; retain only until the patient contract is decided. |
| `POST /api/llm/provider` | deprecated now | Duplicate alias for `/api/llm/provider/select`; remove after callers use the canonical path. |
| `GET /api/llm/providers` and `POST /api/llm/provider/select` | compatibility-only | Legacy-client callers. Selection validates but does not persist provider state; retire or replace when provider selection gains owned state. |
| `POST /api/records/generate` and `POST /api/records/preview` | deprecated now | Legacy-client callers receive gateway 501 responses. Remove after those UI paths are removed or backed by a real gateway-owned record API. |
| `POST /api/records/regenerate`, `POST /api/records/commit`, and `GET /api/records/patient/{id}/history` | deprecated now | Gateway stubs returning 501; no repository caller was found. Remove after confirming external callers are retired or delivering a real gateway-owned record API. |
| `GET /api/records/templates` | supported | Static metadata; retain unless the record UI is retired. |
| `POST /api/transcript/reclassify` | deprecated after speech cutover | Legacy-client caller. Temporary LLM fallback; remove only after authoritative speech results feed the transcript stream and clients no longer call it. |

### Gateway routes not in the migration surface

| Route | Status | Action |
| --- | --- | --- |
| `GET /health` | supported operations | Liveness endpoint; retain. |
| `GET /metrics` | supported operations | Prometheus scrape endpoint; retain and keep non-public at the deployment boundary. |
| `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/profile` | supported | Auth contract; outside this migration. |

## Direct FastAPI routes

The following routes are legacy-only and are deprecated for new callers now.
They must be removed from public exposure first, then deleted only after the
listed replacement is live and callers have migrated.

| FastAPI routes | Replacement / removal gate |
| --- | --- |
| `POST /api/session/start`, `POST /api/session/{id}/end`, `POST /api/session/{id}/transcribe`, `POST /api/session/{id}/pipeline`, `GET /api/session/{id}/pipeline/status`, `POST /api/session/{id}/upload`, `GET /api/session/{id}/documents`, `GET /api/session/{id}/queue`, `PATCH /api/session/{id}/queue/{item}`, `GET /api/session/{id}/record` | Gateway session ingress plus the durable transcript/document model. Do not delete until SessionService callers are eliminated. |
| `POST /api/session/{id}/assistant` | Intent-gated assist runtime using the shared tool registry and receipt-aware retrieval. The current Python `AssistantService` is also a predecessor, not the target executor. |
| `GET /api/records/templates`, `POST /api/records/generate`, `POST /api/records/preview`, `POST /api/records/regenerate`, `POST /api/records/commit`, `GET /api/records/patient/{id}/history` | Gateway-owned record API or explicit retirement of record-generation UI. |
| `POST /api/clinical/suggestions`, `POST /api/clinical/check-allergies`, `POST /api/clinical/check-interactions`, `POST /api/clinical/interpret-labs`, `POST /api/clinical/override` | A gateway-owned safety/clinical API, if retained. Otherwise remove after legacy UI migration. |
| `GET /api/patient/{id}/profile`, `GET /api/patient/{id}/lab-trends`, `GET /api/patient/{id}/risk-score` | Existing Go patient endpoints, after their response contract is made canonical. |
| `POST /api/tts` | A supported gateway TTS proxy, or removal of TTS UI. |
| `POST /api/transcript/reclassify` | Server-side speech/role assignment cutover. |
| `GET /api/llm/providers`, `POST /api/llm/provider/select`, `GET /api/llm/status` | Canonical Go LLM configuration contract or removal of runtime selection. |

## Internal bridge routes: do not deprecate yet

| Route | Why it remains |
| --- | --- |
| `POST /internal/pipeline` | Current Go `pipeline-worker` sends the 16-node LangGraph compile request here. It is removed only when compile-worker owns that work. |
| `POST /internal/audio-segment` | Current audio-worker bridge to the configured speech provider. It remains internal until the Lane A replacement is live. |
| `GET /` on the FastAPI process | Legacy service-identification response. Keep unreachable from public ingress; remove with the FastAPI process. |
| Worker health and metrics routes | Required by deployment probes and observability. |

## Explicitly out of scope for this issue

- Object-storage intake; PostgreSQL `ingest_documents`, `ingest_tasks`, and
  outbox/reconciler work.
- Replacing Redis list/blob session state with the planned transcript stream
  and immutable draft model.
- Executing the new intent gate, fixed executor, or planning agent.

Those replacements are prerequisites for deleting the legacy bridge safely.
