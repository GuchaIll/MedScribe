# Modal Speech Worker

This directory contains a GPU-backed Modal deployment target for the MedScribe
Whisper + pyannote speech worker.

It is meant to back the existing `remote_http` speech provider path, so the Go
gateway and local speech-worker proxy do not need structural changes.

## What It Exposes

- `POST /process-audio`
- `GET /health`

The request contract matches
[server/app/services/speech_worker_service.py](/Users/guchaill/Coding/MedScribe/server/app/services/speech_worker_service.py:80).

## Why Use This

Use Modal when your local machine cannot run:

- `faster-whisper` on a large model
- `pyannote.audio` diarization
- GPU-backed speech inference at low enough latency

This is the intended path for Apple Silicon laptops and lightweight dev
machines.

## Prerequisites

1. Install Modal locally:

```bash
pip install modal
```

2. Authenticate with Modal:

```bash
modal token new
```

3. Create a Hugging Face token with access to the pyannote gated models.

4. Accept the model terms on Hugging Face for:

- `pyannote/speaker-diarization-3.1`

## Create Modal Secrets

Create one secret for pyannote model downloads:

```bash
modal secret create huggingface HF_TOKEN=hf_your_token_here
```

Create one secret for bearer auth between your MedScribe gateway and the Modal
endpoint:

```bash
modal secret create medscribe-speech-worker SPEECH_REMOTE_API_KEY=your_shared_token
```

If you want the endpoint to accept unauthenticated requests during bring-up,
create the same secret with an empty value instead:

```bash
modal secret create medscribe-speech-worker SPEECH_REMOTE_API_KEY=
```

The endpoint only enforces auth when `SPEECH_REMOTE_API_KEY` is non-empty.

## Local Dev Endpoint

Run an ephemeral endpoint while iterating:

```bash
modal serve infra/modal/medscribe_speech_worker.py
```

## Deploy

Deploy a persistent endpoint:

```bash
modal deploy infra/modal/medscribe_speech_worker.py
```

After deploy, Modal will print the public endpoint URL.

## Warm-Start Behavior

The worker is configured to reduce first-request latency in two ways:

- a persistent Modal volume caches Hugging Face model artifacts across
  container restarts
- FastAPI startup preloads Whisper, pyannote diarization, and the speaker
  embedding model before the first live request

You should still expect:

- a slower first request after a fresh deploy or after the warm container is
  replaced
- much faster steady-state requests while the container stays warm

The deployed function keeps `min_containers=1`, so Modal should maintain one
warm replica when traffic is present.

## Wire MedScribe To Modal

Set these values in your MedScribe `.env`:

```env
SPEECH_PROVIDER=remote_http
SPEECH_REMOTE_URL=https://YOUR_MODAL_URL
SPEECH_REMOTE_API_KEY=your_shared_token
```

Then restart the local `speech-worker` container or server process.

## Reference-Sample Role Matching

The current remote worker now accepts the same two onboarding reference clips
already captured by MedScribe:

- `reference_clinician`
- `reference_patient`

It uses a pyannote speaker-embedding model to compare the current utterance
against those two samples and returns the better session-local role match.

This keeps the MVP constrained to a two-speaker encounter:

- one clinician
- one patient

## Current Limitation

This Modal worker performs:

- authoritative Whisper transcription
- pyannote diarization
- primary speaker ID extraction
- session-local clinician/patient role matching from the uploaded reference
  clips

It still does **not** provide persistent voice identity across sessions. The
matching is only for the active encounter and only for the two captured roles.
