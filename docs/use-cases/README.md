# MedScribe Use Case Catalogue

This directory contains elaborated use case documents derived from the current MedScribe architecture, design notes, and implementation details.

## Available Use Cases

1. **[UC-01 - Multimodal RAG Pipeline for Clinical Documentation](./UC-01-multimodal-rag-pipeline.md)**
   - Covers live audio capture, Silero VAD gating, Whisper/Web Speech transcription flow, OCR ingestion, LangGraph orchestration, evidence grounding, validation, and SOAP note generation.

2. **[UC-02 - Three-Tier Persistence and HIPAA-Oriented Data Management](./UC-02-three-tier-persistence-and-hipaa-data-management.md)**
   - Covers the PostgreSQL/pgvector long-term record layer, SQLite checkpoint layer, object storage layer, auditability, encryption requirements, retention, backup, and recovery.

## Source Basis

These use cases were elaborated from the current repository documentation and implementation, especially:

- `README.md`
- `docs/architecture.md`
- `docs/design-decisions.md`
- `server/app/agents/Agents.md`
- `server/app/core/workflow_engine.py`
- `server/app/database/models.py`

## Notes

- The documents describe the intended MedScribe use cases in a form suitable for architecture, product, and review discussions.
- Where the repository contains roadmap or partially implemented capabilities, the use cases explicitly note the current implementation status.
