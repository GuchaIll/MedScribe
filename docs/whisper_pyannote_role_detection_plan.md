# Whisper + pyannote Role Detection Plan

## Goal

Add a server-side speech pipeline that improves transcript quality and assigns
stable `Clinician` / `Patient` roles, while preserving the current frontend UX:

- keep **Silero VAD** in the browser for utterance detection
- replace browser speech recognition as the long-term authoritative transcript
  source with **Whisper**
- use **pyannote** for diarized speaker segmentation
- keep **browser speech synthesis** for audio output
- do **not** introduce a neural TTS or voice-cloning model in this phase

## Why This Matters

The current live transcript depends on the browser's Web Speech API plus a
separate LLM-based reclassification endpoint for speaker labels. That gives a
usable demo flow, but it leaves two important quality problems unresolved:

1. transcript text quality varies by browser and platform
2. speaker-role detection is inferred from text patterns rather than audio

For clinical documentation, role detection is not cosmetic. It directly affects:

- symptom attribution
- medication instruction parsing
- allergy and contraindication reasoning
- auditability of who said what

## Current State

Today the repo behaves like this:

1. browser Silero VAD detects speech start/end
2. browser Web Speech API produces the live transcript
3. transcript text is sent to the backend as utterances
4. an optional LLM route reclassifies messages as `Clinician` / `Patient`

Relevant files:

- [client/medscribe/src/hooks/useVoiceCapture.js](/Users/guchaill/Coding/MedScribe/client/medscribe/src/hooks/useVoiceCapture.js:1)
- [client/v2/src/hooks/useVoiceCapture.ts](/Users/guchaill/Coding/MedScribe/client/v2/src/hooks/useVoiceCapture.ts:1)
- [server/app/api/routes/transcript.py](/Users/guchaill/Coding/MedScribe/server/app/api/routes/transcript.py:1)

## Target State

The upgraded flow should look like this:

1. browser Silero VAD marks voiced utterance boundaries
2. browser captures the voiced audio segment for that utterance
3. Go gateway accepts the voiced segment quickly and publishes it to Kafka
4. a dedicated Whisper + pyannote worker transcribes and diarizes it
5. a role resolver maps speaker IDs to `Clinician` / `Patient`
6. corrected transcript segments are written back to Redis / PostgreSQL
7. UI reconciles the optimistic transcript with the authoritative server result

## Design Principles

- **Do not block the protected hot path.**
  Audio submission must be fast even if Whisper is slow.
- **Keep Silero VAD in the browser.**
  It is already good at low-latency utterance detection and reduces server load.
- **Make Whisper authoritative for text.**
  Browser recognition can remain an optimistic preview during rollout.
- **Treat pyannote as speaker diarization, not final role labeling.**
  `SPEAKER_00` and `SPEAKER_01` still need a role-mapping step.
- **Keep output simple.**
  Browser speech synthesis stays in place; no voice model work in this scope.

## Proposed Service Boundary

### Browser

Responsibilities:

- run Silero VAD
- maintain live encounter UX
- capture voiced audio segments after `onSpeechEnd`
- optionally show browser speech recognition as optimistic text until the
  server transcript arrives

### Go Gateway

Responsibilities:

- accept voiced audio segments
- validate session ownership and session status
- enqueue audio work to Kafka
- seed transcript-job status in Redis
- expose transcript status / corrected segments to the frontend

### Whisper + pyannote Worker

Responsibilities:

- consume voiced audio jobs
- run Whisper on each utterance or micro-batch of utterances
- run pyannote diarization on the same segment or sliding session window
- emit transcript segments with speaker IDs and timing metadata
- call a role resolver to produce `Clinician` / `Patient`

### Redis / PostgreSQL

Responsibilities:

- Redis: active transcript state, pending transcript jobs, speaker-role cache
- PostgreSQL: durable transcript ledger and finalized corrected transcript

## Kafka Topics

The dev stack already creates topics that can be reused or extended:

- `audio.ingest`
- `transcript.segments`

Recommended usage:

- `audio.ingest`
  Browser-to-backend voiced audio jobs
- `transcript.segments`
  Authoritative Whisper transcript segments plus role labels

Optional later topics:

- `transcript.corrections`
- `diarization.events`

## API / Message Contracts

### New ingest endpoint

Recommended endpoint:

- `POST /api/session/{id}/audio-segment`

Payload should include:

- `session_id`
- `segment_id`
- `started_at_ms`
- `ended_at_ms`
- `mime_type`
- `audio_blob` or uploaded file reference
- optional optimistic browser transcript text

### Worker output contract

Each emitted transcript segment should include:

- `session_id`
- `segment_id`
- `start`
- `end`
- `text`
- `speaker_id`
- `speaker_role`
- `role_confidence`
- `transcription_confidence`
- `source = "whisper_pyannote"`

## Role Detection Strategy

pyannote alone gives stable speaker identities, not clinical roles. The worker
should therefore maintain a **role resolver** per session.

Important constraint:

- pyannote answers **who spoke when** with anonymous labels such as
  `SPEAKER_00` and `SPEAKER_01`
- those labels are scoped to the current audio/session and do not identify a
  known person by name
- there is no built-in voice identity database or persistent clinician/patient
  mapping

That means the role resolver needs extra session-scoped supervision rather than
just raw diarization output.

### Phase 1 role resolver

Use an explicit **reference-sample onboarding** flow at session start.

For the MVP, constrain the encounter to exactly two roles:

1. collect one short clinician voice sample
2. collect one short patient voice sample
3. store both reference clips in session state
4. let the downstream resolver map anonymous diarization speakers against those
   references

This keeps role assignment grounded in audio rather than pure transcript
heuristics, while staying within a two-speaker clinical encounter assumption.

### Phase 1.5 resolver fallback

Use deterministic heuristics only as a session-local fallback when reference
matching is incomplete:

1. first sustained speaker near session start is likely `Clinician`
2. question-heavy, instruction-heavy speech biases toward `Clinician`
3. symptom-description and answer-heavy speech biases toward `Patient`
4. once mapped, persist speaker-to-role mapping in Redis for the session

### Phase 2 role resolver

Use the existing LLM reclassification route only as a low-confidence fallback:

- trigger when heuristic confidence is below threshold
- run only on ambiguous speaker mappings
- cache the result per speaker/session

This keeps pyannote central while avoiding an expensive LLM call on every turn.

## Rollout Plan

### Phase 0: Claim cleanup

- update docs so current browser-based transcription is described honestly
- stop implying Whisper + pyannote are already on the active path
- document the intended server-side speech architecture

### Phase 1: Browser audio capture

- capture voiced audio blobs from the existing VAD flow
- preserve current optimistic transcript UI
- send utterance audio to a new backend endpoint
- add a session-start voice check that captures one clinician and one patient
  reference sample for MVP role resolution

Definition of done:

- voiced audio segment upload works without breaking current session UX
- two-speaker role onboarding state is captured at session start

### Phase 2: Gateway ingest lane

- add `POST /api/session/{id}/audio-segment`
- publish audio jobs to `audio.ingest`
- store pending transcript job state in Redis
- forward queued jobs through a dedicated gateway audio proxy consumer so the
  hot path stays non-blocking

Definition of done:

- audio upload is fast and non-blocking
- slow workers do not block encounter capture

### Phase 3: Whisper worker

- add a dedicated Python worker service
- run `faster-whisper` for segment transcription
- publish transcript results to `transcript.segments`
- support a `remote_http` speech provider mode for development machines that
  cannot run heavy local Whisper / pyannote models
- add a Modal-hosted GPU deployment target so Apple Silicon and lightweight dev
  machines can use the same speech contract without local model inference

Definition of done:

- authoritative server transcript is produced for each utterance

### Phase 4: pyannote diarization + role resolver

- add session-aware diarization processing
- map diarized speaker IDs to `Clinician` / `Patient`
- use clinician/patient reference clips plus a pyannote speaker embedding model
  for the MVP matcher
- persist role mapping in Redis for the active session

Definition of done:

- speaker-role labels are stable across a session
- the existing LLM reclassifier is no longer the primary role path

### Phase 5: Transcript reconciliation

- UI replaces optimistic browser transcript text with authoritative server text
- UI updates speaker labels when the backend result arrives
- session end flushes corrected transcript to durable storage

Definition of done:

- the transcript visible to the clinician converges to the server result
- the durable transcript is Whisper-based, not browser-only

## Non-Goals

Not in scope for this phase:

- replacing Silero VAD in the browser
- building a neural TTS stack
- voice cloning
- full duplex streaming audio conversations
- replacing LangGraph or the OCR pipeline

## Main Risks

- browser audio capture and permission handling vary across browsers
- pyannote produces anonymous speaker IDs, so role mapping still needs product
  logic
- diarization quality can degrade on overlapping speech and noisy room audio
- full-session diarization may require windowing or incremental reconciliation

## Acceptance Criteria

- Silero VAD remains the frontend utterance detector
- browser speech synthesis remains the only audio output path
- Whisper becomes the authoritative transcript source
- pyannote becomes the primary speaker identity source
- clinician/patient role labels are session-stable and auditable
- the current LLM transcript reclassifier becomes fallback-only
