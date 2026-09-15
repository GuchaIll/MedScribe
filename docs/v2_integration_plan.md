# `client/v2` Integration Plan

`client/v2/` is the Lovable-rebuilt frontend (originally
`whisperwave-transcribe/`). It has a polished UI shell, Supabase auth, and a
mocked transcript/patient flow. To replace `client/medscribe/` as the
production UI it needs the clinical features that only exist in the original
CRA codebase today — most importantly the **OCR field comparator / conflict
resolver** that drives the human-review gate.

This document is the migration roadmap. It does not include code changes
beyond the docker-compose wiring (handled separately). Both clients run side
by side during the migration:

- `client/medscribe/` — current production UI, served at `:3000` (dev) / `:80`
  (demo)
- `client/v2/`        — new Lovable-based UI, served at `:3100` (dev)

The original UI must remain functional until v2 reaches feature parity.

---

## Runtime Contract v2 must respect

The replacement frontend must assume the following backend contract:

1. **Transcription is always-on and non-blocking.**
   Sending an utterance must never wait on OCR, LangGraph, note generation, or
   physician review.
2. **OCR and note generation are async by default.**
   Upload, SOAP generation, discharge generation, and patient-review packages
   may complete later and should be surfaced as status-driven UI.
3. **Redis-backed active session views are first-class.**
   The UI should expect fast reads for transcript, draft notes, review queue,
   and assistant responses from the active session cache.
4. **End session is a durability action.**
   The UI should treat session end as "flush and close", not just "hide the
   recorder".

---

## What v2 has today

| Surface                              | Status in v2          | Source                                            |
| ------------------------------------ | --------------------- | ------------------------------------------------- |
| Routing                              | `react-router-dom` 6  | `App.tsx`                                         |
| Auth (sign-in / sign-up / reset)     | Supabase              | `pages/Auth.tsx`, `hooks/useAuth.tsx`             |
| Route protection                     | `ProtectedRoute`      | `components/ProtectedRoute.tsx`                   |
| Profile (display name, avatar)       | Supabase `profiles`   | `pages/Settings.tsx`, `hooks/useProfile.tsx`      |
| Transcript bubble feed               | In-memory mock store  | `components/clinical/Transcript.tsx`              |
| Waveform + mic capture (no upload)   | Heuristic VAD         | `components/clinical/Waveform.tsx`                |
| Tools bar (Upload / SOAP / Discharge / Patient summary) | Mocked strings | `components/clinical/ToolsBar.tsx` |
| Patient page (Overview / BGL / Meds / Labs / Goals) | Mocked data | `pages/PatientProfile.tsx`, `components/patient/*` |
| Schedule page                        | Mocked recents        | `pages/Schedule.tsx`                              |
| PDF export                           | Hand-rolled byte writer | `components/clinical/Transcript.tsx`             |

## What v2 is missing (lives in `client/medscribe/`)

| Feature                               | Source in original                                                       | Backend it talks to                          |
| ------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------- |
| **OCR field comparator + resolver**   | `components/upload/DocumentViewPanel.jsx` (961 LoC)                      | `/api/session/:id/upload`, `/api/session/:id/record` |
| **Patient-record change-review card** | `components/chat/AgentCard.jsx` (1415 LoC, `CHANGE_COLORS` + `conflictDetails`) | Pipeline output `validation_report.conflicts` |
| Real transcription pipeline trigger   | `components/MedicalTranscription.jsx` (963 LoC)                          | `/api/session/start`, `/api/session/:id/pipeline`, `/api/session/:id/pipeline/status` |
| Real speech capture (VAD + Web Speech API) | `hooks/useVoiceCapture.js`, `useSpeechCapture.js`                   | client-only                                  |
| LLM provider selection modal          | `components/modals/LLMProviderModal.jsx`                                 | `/api/llm/providers`, `/api/llm/provider/select` |
| Document upload modal                 | `components/upload/UploadPanel.jsx`                                      | `/api/session/:id/upload`                    |
| Pipeline-node progress sidebar        | `components/sidebar/PipelineStepsSidebar.jsx` + `constants.js::PIPELINE_NODES` | `/api/session/:id/pipeline/status`     |
| Live-session structured record polling | `getSessionRecord` poll in `MedicalTranscription.jsx`                   | `/api/session/:id/record`                    |
| Voice "Assistant, …" handler          | `askAssistant` in `api.js`                                               | `/api/session/:id/assistant`                 |
| Drug-interaction / allergy check      | `getClinicalSuggestions`, `checkAllergies`, `checkInteractions`          | `/api/clinical/*`                            |
| Record / SOAP / Discharge generation   | `generateRecord`, `previewRecord`                                       | `/api/records/generate`, `/api/records/preview` |
| TTS                                   | `speakText` in `api.js`                                                  | `/api/tts`                                   |

`api.js` is the canonical surface — every endpoint in it must have a v2
equivalent. There are ~25 endpoints across 7 routers
(session / llm / transcript / records / clinical / tts / patient / upload).

---

## Auth Decision

**Keep v2's existing Supabase auth flow exactly as-is.** The original
`client/medscribe` has no client-side auth at all — the Python backend hands
out an opaque `session_id` from `/api/session/start` that the UI just holds
in component state. There is therefore nothing to migrate; the two systems
live at different layers:

- **Supabase session** (in v2) → "is this user allowed to use the app at all"
- **MedScribe `session_id`** (from `/api/session/start`) → "which clinical
  encounter is the user currently inside"

Both will coexist. The Supabase JWT is *not* yet forwarded to the Python
API — that bridging step is its own ticket and is called out in
[`demo_deployment.md`](./demo_deployment.md#if-you-need-a-more-prod-like-next-step)
step 2. Until then, the Python API trusts in-process state, and the gateway's
JWT validation is bypassed for v2 just like it currently is for
`client/medscribe`.

---

## Target Architecture for v2

```
src/
├── api/
│   ├── client.ts          # apiFetch wrapper, BASE = '/api', error handling
│   ├── session.ts         # startSession, endSession, sendTranscription, runPipeline, getPipelineStatus, getSessionRecord
│   ├── llm.ts             # getLLMProviders, getLLMStatus, selectLLMProvider
│   ├── records.ts         # generateRecord, previewRecord, getTemplates
│   ├── clinical.ts        # getClinicalSuggestions, checkAllergies, checkInteractions
│   ├── upload.ts          # uploadDocuments, prepareUpload
│   ├── transcript.ts      # reclassifyTranscript
│   ├── patient.ts         # getPatientProfile
│   ├── assistant.ts       # askAssistant
│   └── tts.ts             # speakText
├── hooks/
│   ├── useAuth.tsx        # (existing, unchanged)
│   ├── useProfile.tsx     # (existing, unchanged)
│   ├── useVoiceCapture.ts # PORTED from client/medscribe — replaces Waveform's mock
│   ├── useTimer.ts        # PORTED
│   ├── useNotify.ts       # PORTED (toast wrapper)
│   └── useSession.ts      # NEW — wraps startSession/endSession + sessionId state
├── components/
│   ├── ocr/
│   │   ├── DocumentViewer.tsx       # PORT of DocumentViewPanel.jsx, broken up
│   │   ├── FieldComparator.tsx      # NEW — extracted from DocumentViewPanel (the diff/conflict UI)
│   │   ├── ConflictResolver.tsx     # NEW — interactive conflict resolution (extracted)
│   │   └── UploadModal.tsx          # PORT of UploadPanel.jsx
│   ├── pipeline/
│   │   ├── PipelineProgress.tsx     # PORT of PipelineStepsSidebar.jsx
│   │   ├── pipelineNodes.ts         # PORT of PIPELINE_NODES from constants.js
│   │   └── ReviewChangesCard.tsx    # PORT of the AgentCard "Review Patient Record Changes" sub-component
│   ├── llm/
│   │   └── LLMProviderModal.tsx     # PORT of LLMProviderModal.jsx
│   └── clinical/ … (existing)
└── pages/
    ├── Index.tsx          # rewires to use useSession + real transcript stream
    ├── PatientProfile.tsx # gains a "Review record changes" tab fed by pipeline output
    └── DocumentReview.tsx # NEW route /document/:id — full-screen OCR comparator
```

### Routes to add (v2)

| Path                  | Component             | Notes                                  |
| --------------------- | --------------------- | -------------------------------------- |
| `/document/:docId`    | `DocumentReview`      | Full-screen OCR field comparator       |
| `/patient/:patientId` | `PatientProfile`      | Replace hardcoded route with real ID   |
| `/session/:sessionId` | `Index`               | Optional — encounter-scoped transcript |

The current `/patient` (no ID) and `/` are kept as default redirects to the
above during the transition.

---

## Migration Phases

### Phase 1 — Plumbing (no UX change)

Goal: v2 can talk to the Python API and stand up a real session, while still
showing the mocked transcript.

1. Port `client/medscribe/src/api/api.js` → `client/v2/src/api/*.ts` with
   typed return shapes. Use `apiFetch` with the same `/api` base path.
2. Add a `useSession` hook that owns `sessionId`, `sessionActive`, and
   start/end mutations.
3. Add `useVoiceCapture` + `useSpeechCapture` + `useTimer` + `useNotify`
   from the original — these are framework-agnostic React hooks.
4. Replace the heuristic VAD in `components/clinical/Waveform.tsx` with
   `useVoiceCapture` (Silero VAD via `@ricky0123/vad-web` from CDN). Keep
   the existing SVG visualisation.
5. Wire `Waveform`'s `onUtterance` to `sendTranscription(sessionId, text)`
   and append the returned turn via `transcriptStore.addTurn`.

Acceptance: a logged-in user can press Record and see their words appear in
the transcript bubble feed, fed from the real backend, without waiting on any
background worker.

### Phase 2 — Upload + OCR comparator

Goal: bring across the highest-value piece — the OCR field comparator and
conflict resolver.

1. Port `UploadPanel.jsx` → `components/ocr/UploadModal.tsx`. Wire the
   "Upload Document" tool in `ToolsBar.tsx` to open it.
2. Port `DocumentViewPanel.jsx` → `components/ocr/DocumentViewer.tsx`,
   splitting the 961-line file into:
   - `DocumentViewer.tsx` — split-pane shell (PDF preview + form)
   - `FieldComparator.tsx` — the editable field grid with
     `normal | modified | lowConf | conflict` styling driven by
     `_low_confidence` / `_conflicts` / `_db_seeded_fields` markers
     produced by the OCR pipeline
   - `ConflictResolver.tsx` — interactive resolution UI (accept extracted /
     keep DB / edit manually) — currently embedded in `DocumentViewPanel`'s
     conflict tooltip
3. Add `pages/DocumentReview.tsx` mounted at `/document/:docId`.
4. Port `CHANGE_COLORS` and `LOW_CONF` thresholds to a shared
   `src/lib/clinical.ts`. Replace the inline-style design (`style={...}`)
   with Tailwind classes consistent with the rest of v2's glass-panel
   aesthetic; tone classes already exist in
   `components/clinical/_shared.tsx`.

Acceptance: a user can upload a document, see OCR extraction overlaid on
the structured record, and resolve conflicts before approved changes are
persisted.

### Phase 3 — Pipeline trigger + progress

Goal: replace `ToolsBar` mock SOAP/discharge with the real 17-node pipeline.

1. Port `PIPELINE_NODES` and `PipelineStepsSidebar.jsx` →
   `components/pipeline/PipelineProgress.tsx`. The shared `Panel` /
   `SectionHeader` primitives can be reused.
2. Wire the "Session Summary" tool in `ToolsBar.tsx` to call
   `runPipeline(sessionId, patientId, doctorId, segments)` instead of
   appending the canned SOAP string.
3. Poll `getPipelineStatus` while running; render node progress in a
   right-side panel (replaces nothing currently in v2 — net-new UI).
4. On completion append the returned `clinical_note` as a Scribe bubble
   via `transcriptStore.addTurn({ kind: 'soap', text })`. The existing
   `FormattedScribe` renderer already handles section detection.

Acceptance: the v2 "Generate SOAP" flow runs the real pipeline end-to-end
and shows live progress, but the transcript capture flow remains uninterrupted
while that work happens in the background.

### Phase 4 — Record changes review (AgentCard)

Goal: the human-review gate where the physician approves/rejects
field-level changes after pipeline completion.

1. Extract the "Review Patient Record Changes" sub-card from `AgentCard.jsx`
   (lines ~440–680) into `components/pipeline/ReviewChangesCard.tsx`.
2. Render it as a Scribe-kind bubble in the transcript when the pipeline
   returns `validation_report.requires_review === true`.
3. The `onApprove` callback writes the approved record via
   `/api/session/:id/record` (new endpoint or existing — confirm with
   `server/app/routers/session.py`).

Acceptance: the human-review-gate node's output is actionable in v2.

### Phase 5 — Records / clinical / patient profile

Goal: replace the remaining mocks (Patient page, allergy/drug-interaction
checks, record templates).

1. Port `getPatientProfile` → React Query hook
   `usePatientProfile(patientId)`. Delete `data/patientMock.ts` and wire
   each `components/patient/*.tsx` card to live data.
2. Surface `getClinicalSuggestions` (allergy alerts, drug interactions) as
   chips on the patient header card and as inline warnings in the
   prescribe flow.
3. Add a patient-profile question path that can render:
   - cached active-session answers
   - RAG-grounded historical answers
   - exact DB/tool lookup answers
   without forcing the user through note generation first.
4. Replace `Transcript.tsx`'s hand-rolled PDF byte writer with
   `generateRecord(..., 'pdf')` from the backend (server-rendered, much
   more reliable).

Acceptance: no mocks left in v2; every clinical surface is backed by an
API call.

### Phase 7 — Session finalization

Goal: make "End session" explicitly durable.

1. `useSession.endSession()` should display a flushing / finalizing state.
2. The UI should keep polling until the backend confirms session closure and
   final persistence status.
3. If unresolved review items remain, present them as explicit pending items
   rather than silently dropping them.

Acceptance: ending a session clearly communicates that in-session transcript,
approved changes, and finalized notes have been durably handled.

### Phase 6 — LLM provider modal + assistant + TTS

Goal: feature parity for the smaller surfaces.

1. Port `LLMProviderModal.jsx` and gate sign-in completion behind LLM
   provider selection (matches current behavior).
2. Add the "Assistant, …" wake-phrase handler in `useVoiceCapture`
   (regex match in `onUtterance`) and call `askAssistant`.
3. Wire `speakText` to a "speak this" affordance on Scribe bubbles.

Acceptance: feature parity with `client/medscribe`. The CRA build can be
removed from `docker-compose.yml`.

---

## Open Questions

1. **Encounter ID**. The transcript header currently shows the hardcoded
   `Encounter #4821`. Once `useSession` lands, this should come from the
   route. Decide whether to use the Python session ID (UUID) or the
   Supabase `auth.users.id` × server-generated encounter ID.
2. **Supabase ↔ Python identity bridge**. Today the Python backend uses
   `auth.users.id` only via the gateway when it's configured; the demo
   path bypasses auth entirely. Decide whether v2 should send the Supabase
   JWT in an `Authorization: Bearer …` header for the Python API to verify
   against Supabase's JWKS, or wait for the gateway path to be finished.
   See [`demo_deployment.md`](./demo_deployment.md#known-limitations).
3. **State sync between Supabase profile and patient record.** The Python
   pipeline writes structured records to Postgres (`server/app/db/`).
   Supabase auth lives in Supabase Postgres. Decide whether to keep these
   separate (auth-only Supabase, clinical data in the MedScribe DB) or to
   migrate auth onto Postgres via Supabase self-hosted.
4. **Profile-row identity collision**. Supabase `profiles.id` references
   `auth.users.id`; the MedScribe doctor identity in the Python pipeline
   is currently a separate string. Pick which ID flows where before
   Phase 5.

---

## Out of Scope for This Plan

- Removing `client/medscribe/`. That happens after Phase 6 acceptance, in a
  separate cleanup PR.
- Changing the Go gateway path or the Kafka ingestion topology.
- HIPAA hardening (TLS, session timeout, audit log, encryption at rest).
  Tracked separately in [`demo_deployment.md`](./demo_deployment.md).
