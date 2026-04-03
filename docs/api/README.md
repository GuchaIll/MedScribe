# MedScribe API Documentation

## Overview

MedScribe exposes a FastAPI REST backend on port **3001**. All routes are prefixed with `/api` except where noted.

This documentation is split by controller file, each covering the endpoints, request/response schemas, and usage examples for one area of the system.

---

## Controller Index

| Controller File | Base Path | Description |
|-----------------|-----------|-------------|
| [session.md](session.md) | `/api/session` | Session lifecycle, transcription, LangGraph pipeline, document upload, OCR review queue |
| [assistant.md](assistant.md) | `/api/session/{id}/assistant` | AI assistant — RAG-based clinical Q&A |
| [clinical.md](clinical.md) | `/api/clinical` | Clinical decision support — allergy checks, drug interactions, lab interpretation, override logging |
| [patient.md](patient.md) | `/api/patient` | Longitudinal patient view — lab trends, risk score, full profile |
| [records.md](records.md) | `/api/records` | Medical record generation, preview, feedback-driven regeneration, finalisation, version history |
| [transcript.md](transcript.md) | `/api/transcript` | Transcript utilities — LLM-based speaker reclassification |
| [tts.md](tts.md) | `/api/tts` | Text-to-speech synthesis via ElevenLabs |

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
