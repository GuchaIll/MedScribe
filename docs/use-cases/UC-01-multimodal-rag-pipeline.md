# UC-01 - Multimodal RAG Pipeline for Clinical Documentation

| Field | Value |
|---|---|
| Use Case ID | UC-01 |
| Name | Multimodal RAG Pipeline for Clinical Documentation |
| Scope | Clinical transcription, document understanding, evidence-grounded note generation |
| Primary Actors | Physician, Medical Assistant |
| Supporting Actors | Patient, MedScribe System, Groq LLM API, PostgreSQL/pgvector |
| Trigger | A clinical session is started and the clinician requests record generation |

## 1. Goal

Enable MedScribe to transform multimodal encounter input into an evidence-grounded clinical record by combining:

- speech capture and transcription,
- uploaded clinical document ingestion,
- LangGraph-orchestrated reasoning,
- retrieval over patient and session evidence,
- deterministic validation,
- and structured note generation.

This use case directly supports the MedScribe objective of reducing documentation burden while preserving traceability, reviewability, and clinical context.

## 2. Summary

The physician starts a session, dictates findings, and may upload prior clinical documents. The system captures audio through a VAD-gated speech workflow, processes uploaded documents through OCR, merges both modalities into a single clinical context, and runs the LangGraph workflow to extract facts, retrieve supporting evidence, validate outputs, and generate a SOAP note plus structured record.

Current repository status:

- **Silero VAD** is actively integrated on the client.
- **Web Speech API** is the active browser transcription path.
- **Whisper** exists in the server stack and roadmap, but current docs note it is not the active production transcription path.
- **LangGraph orchestration**, **OCR**, **validation**, **grounding**, and **PostgreSQL/pgvector persistence** are implemented architectural pillars.

## 3. Preconditions

1. The user is authenticated and authorized to create or update a clinical session.
2. A patient is selected or a new patient encounter is initiated.
3. Backend services are available, including FastAPI, database connectivity, and configured model providers.
4. Browser microphone permissions are granted for live transcription.
5. Object and file storage paths are available for uploaded artifacts and generated outputs.
6. LangGraph checkpoint storage is writable.

## 4. Postconditions

### Success

1. A session transcript and associated document artifacts are processed.
2. A structured clinical record is produced.
3. A SOAP note is generated.
4. Evidence links and confidence metadata are attached to extracted facts.
5. Session outputs and audit data are persisted.

### Failure

1. The system records the failure reason and preserves available progress.
2. Partial workflow state remains recoverable through checkpointing where supported.
3. The clinician can retry or route the case for manual review.

## 5. Primary Actors and Responsibilities

### Physician

- Starts and ends the encounter session.
- Speaks clinical observations, assessments, and plans.
- Uploads or reviews supporting documents when needed.
- Reviews generated outputs and resolves flagged issues.

### Medical Assistant

- Uploads prior visit documents, referral letters, lab reports, or scanned forms.
- Supports session setup and patient context preparation.

### Patient

- Provides spoken history and answers during the encounter.

### MedScribe System

- Detects speech activity.
- Transcribes or accepts transcribed segments.
- Processes uploaded documents.
- Orchestrates extraction, retrieval, validation, and note generation.
- Persists final outputs and audit artifacts.

## 6. Main Success Scenario

### 6.1 Session Initialization

1. The physician opens MedScribe and starts a session.
2. The system creates a new session identifier and loads any available patient context.
3. Prior records, allergies, medications, and patient history become available to the workflow.

### 6.2 Audio Intake

4. The client-side Silero VAD monitors incoming microphone audio.
5. When speech begins, the system opens the transcription path.
6. Transcript segments are produced and associated with the active session.
7. The process repeats throughout the encounter until sufficient dialogue is captured.

### 6.3 Document Intake

8. The physician or assistant uploads one or more documents.
9. The system stores the uploaded artifact and executes the OCR pipeline.
10. The OCR pipeline performs page splitting, preprocessing, layout detection, handwriting detection, extraction, normalization, classification, field extraction, and conflict detection.
11. The resulting document artifact is attached to the session.

### 6.4 Multimodal Fusion

12. The clinician triggers note generation.
13. The LangGraph workflow begins with patient context loading and multimodal ingestion.
14. Transcript segments and OCR artifacts are normalized into chunkable workflow input.

### 6.5 Retrieval-Augmented Processing

15. The system cleans and normalizes transcription content.
16. The system segments conversation and document content into clinically meaningful chunks.
17. Candidate facts are extracted from the chunk set.
18. Diagnostic reasoning enriches interpretation of the extracted facts.
19. The evidence retrieval stage queries pgvector-backed embeddings to ground extracted facts against source chunks and prior context.
20. The system fills the structured record schema.

### 6.6 Validation and Record Generation

21. Clinical suggestions are computed, including deterministic safety checks such as allergies and interaction review.
22. The record is validated against schema and confidence rules.
23. If valid, the system generates the SOAP note.
24. Outputs are packaged and persisted.
25. The physician reviews the generated note and structured record.

## 7. LangGraph Workflow Responsibilities

The use case relies on the following workflow responsibilities:

1. **Load patient context** - retrieve prior patient facts and records.
2. **Ingest** - unify transcript and OCR artifacts.
3. **Clean and normalize** - remove disfluencies and standardize clinical language.
4. **Segment** - create clinically coherent chunks.
5. **Extract candidates** - identify candidate symptoms, diagnoses, medications, labs, and plans.
6. **Diagnostic reasoning** - support interpretation and likely condition framing.
7. **Retrieve evidence** - ground fields through semantic retrieval.
8. **Fill record** - map facts into the structured schema.
9. **Clinical suggestions** - run deterministic clinical checks.
10. **Validate** - enforce contracts, score confidence, and detect contradictions.
11. **Repair / conflict resolution / review gate** - handle incomplete or conflicting output.
12. **Generate note** - produce clinician-facing documentation.
13. **Persist results** - write outputs and trace artifacts.

## 8. Alternative and Exception Flows

### A1. Human Review Required

If validation or conflict resolution marks the record as needing review:

1. The workflow flags the record for review.
2. Checkpointed state allows the case to be resumed where supported.
3. The physician reviews unresolved issues before final acceptance.

### A2. Document Parsing Partially Fails

If one uploaded document or page cannot be fully parsed:

1. The system continues processing available pages or files.
2. The artifact is marked with parsing issues.
3. The workflow proceeds with the successfully extracted content.

### A3. Transcription Quality Is Insufficient

If live transcription is incomplete or low quality:

1. The clinician may continue dictation, retry, or manually correct content.
2. Uploaded documents and patient context still participate in the workflow.
3. Validation and review steps compensate by flagging uncertain fields.

### A4. Whisper Not Active in Current Runtime

Because current repository docs identify Whisper as present but not the active runtime transcription path:

1. The live workflow uses Silero VAD plus browser transcription.
2. Whisper remains a designed and documented enhancement path for server-side STT.
3. The overall use case remains valid because the orchestration and downstream RAG stages are unchanged.

### A5. LLM or Retrieval Failure

If an external model call or retrieval stage fails:

1. The system records the failure in workflow state and logs.
2. The session does not silently finalize an invalid record.
3. The clinician is informed that manual review or retry is required.

## 9. Business Rules

1. Every extracted clinical fact must retain provenance to a source utterance, document region, or retrieved chunk.
2. Confidence and validation rules must be applied before final persistence.
3. Deterministic checks are preferred for safety-sensitive logic such as allergies and medication conflicts.
4. Human review remains the fallback for unresolved conflicts or low-confidence outputs.
5. Session-level progress must remain observable to support clinician trust and operational transparency.

## 10. Data Inputs

The use case accepts:

- live microphone audio,
- session transcript segments,
- uploaded PDFs and images,
- patient master data,
- prior finalized records,
- medication and allergy history,
- existing semantic embeddings and stored evidence.

## 11. Data Outputs

The use case produces:

- session transcript,
- extracted candidate facts,
- evidence map,
- structured record,
- SOAP note,
- validation report,
- clinical suggestions,
- audit trail entries,
- persisted embeddings for future retrieval.

## 12. Quality Attributes

### Accuracy

- Clinical fields should be grounded to evidence.
- Validation contracts should prevent obviously invalid values from being finalized.

### Traceability

- Every major workflow step should contribute traceable status or audit context.
- Generated outputs should remain reviewable against their sources.

### Resilience

- Checkpointing should preserve workflow state across interruption or failure.
- Multimodal processing should continue when one modality is only partially successful.

### Extensibility

- New nodes, tools, or retrieval sources can be added without redesigning the entire use case.

## 13. Assumptions

1. Clinical users prefer a single workflow that combines dictation, prior context, and scanned records.
2. Evidence-grounded generation is required for trust in AI-assisted documentation.
3. The same workflow should support both new encounters and follow-up visits.
4. The design must allow future migration from browser STT to server-side Whisper without changing downstream orchestration semantics.

## 14. Acceptance Criteria

This use case is satisfied when MedScribe can:

1. start a session and capture encounter input,
2. combine live speech-derived text with uploaded document content,
3. run the LangGraph workflow across normalization, extraction, retrieval, validation, and generation stages,
4. produce a structured clinical record and SOAP note,
5. attach evidence and confidence context to outputs,
6. and persist the result with audit-friendly workflow traceability.
