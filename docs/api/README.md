# MedScribe API Documentation

## Overview

The Go gateway on port **8080** is the supported public API ingress. The
FastAPI process on port **3001** remains an internal migration bridge for the
LangGraph compile path and legacy OCR implementation; its `/api` routes are
not a second supported public surface.

Read [migration-status.md](migration-status.md) before using a route described
in this directory. These controller-oriented documents primarily describe the
legacy Python implementation and are retained only while gateway replacements
are being delivered.

---

## Legacy controller index

| Controller File | Base Path | Description |
|-----------------|-----------|-------------|
| [session.md](session.md) | `/api/session` | Session lifecycle, transcription, LangGraph pipeline, document upload, OCR review queue |
| [assistant.md](assistant.md) | `/api/session/{id}/assistant` | AI assistant — RAG-based clinical Q&A |
| [clinical.md](clinical.md) | `/api/clinical` | Clinical decision support — allergy checks, drug interactions, lab interpretation, override logging |
| [patient.md](patient.md) | `/api/patient` | Longitudinal patient view — lab trends, risk score, full profile |
| [records.md](records.md) | `/api/records` | Medical record generation, preview, feedback-driven regeneration, finalisation, version history |
| [transcript.md](transcript.md) | `/api/transcript` | Transcript utilities — LLM-based speaker reclassification |
| [tts.md](tts.md) | `/api/tts` | Text-to-speech synthesis via ElevenLabs |

## Supported public contract

The Go router in `services/api/internal/controller/http/router.go` is the
authoritative public route list. Its session pipeline status endpoint merges
the gateway's terminal result with Python's per-node progress record.

- Use `/api/session/{id}/pipeline` to queue a compile run, then poll
  `/api/session/{id}/pipeline/status`.
- Do not call FastAPI `/api/session/*`, `/api/records/*`, `/api/clinical/*`,
  `/api/patient/*`, `/api/tts`, or `/api/transcript/*` from new clients.
- Internal worker routes are not public contracts: `/internal/pipeline` and
  `/internal/audio-segment` remain bridge-only until their replacements land.

---

## Shared Conventions

- All request and response bodies are JSON unless noted otherwise.
- Timestamps use ISO-8601 format (`YYYY-MM-DDTHH:MM:SSZ`).
- String identifiers (session IDs, patient IDs, record IDs) are treated as opaque strings.
- Endpoints degrade gracefully when the PostgreSQL database is unavailable unless the database is explicitly required (e.g., `POST /api/records/commit`).
- HIPAA audit log entries are written for all physician override and record finalisation actions.

---

## Environment Variables

| Variable | Required By | Description |
|----------|-------------|-------------|
| `GROQ_API_KEY` | Session pipeline, transcript reclassification | Groq API key for LLM inference (llama-3.3-70b-versatile) |
| `ELEVENLABS_API_KEY` | TTS | ElevenLabs API key for speech synthesis |
| `ELEVENLABS_VOICE_ID` | TTS | Override the default ElevenLabs voice (default: Rachel) |
| `ELEVENLABS_MODEL_ID` | TTS | Override the ElevenLabs model (default: `eleven_turbo_v2`) |
| `DATABASE_URL` | All DB-backed endpoints | PostgreSQL connection string |
| `UPLOAD_DIR` | Session upload | Directory for uploaded documents (default: `storage/uploads`) |
