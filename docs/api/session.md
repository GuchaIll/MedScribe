# Session API Documentation

## 1. Overview

**Base Router Path:** `/api/session`

This section covers the session lifecycle endpoints. A session represents a single clinical encounter. It is created before transcription begins, accumulates transcript utterances and uploaded documents, triggers the full LangGraph processing pipeline, and is explicitly ended when the encounter is complete. All OCR document handling and the modification review queue are also scoped to a session.

---

## 1.1 Interface Definitions

### SessionStartResponse
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique session identifier (UUID) |
| `message` | string | Confirmation message |

### SessionEndResponse
| Field | Type | Description |
|-------|------|-------------|
| `message` | string | Confirmation message |

### TranscribeRequest
| Field | Type | Description |
|-------|------|-------------|
| `text` | string \| null | Transcribed utterance text |
| `speaker` | string | Speaker label, defaults to `"Unknown"` |

### TranscribeResponse
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session the utterance belongs to |
| `speaker` | string | Normalised speaker label |
| `transcription` | string | Stored utterance text |
| `source` | string | Source identifier |
| `agent_message` | string \| null | Optional agent commentary |

### TranscriptSegmentSchema
| Field | Type | Description |
|-------|------|-------------|
| `start` | number | Segment start offset in seconds |
| `end` | number | Segment end offset in seconds |
| `speaker` | string \| null | Speaker label |
| `raw_text` | string | Raw transcript text |
| `confidence` | string \| null | ASR confidence label |

### RunPipelineRequest
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `patient_id` | string | Patient identifier |
| `doctor_id` | string | Clinician identifier |
| `segments` | TranscriptSegmentSchema[] | Transcript segments to process |
| `is_new_patient` | boolean | When `true`, skips DB lookups for prior patient history |

### RunPipelineResponse
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `clinical_note` | string \| null | LLM-generated SOAP note |
| `structured_record` | object \| null | Filled StructuredRecord dict |
| `clinical_suggestions` | object \| null | Allergy / drug interaction results |
| `validation_report` | object \| null | Validation and conflict report |
| `message` | string \| null | Status message |

### PipelineStatusResponse
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `status` | `"pending"` \| `"running"` \| `"completed"` \| `"failed"` | Overall pipeline status |
| `current_node` | string \| null | Name of the last-completed LangGraph node |
| `started_at` | string \| null | ISO-8601 start timestamp |
| `completed_at` | string \| null | ISO-8601 completion timestamp |
| `error` | string \| null | Error message if status is `"failed"` |
| `nodes` | NodeStatus[] | Per-node execution details (see below) |

### NodeStatus
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Internal node name |
| `label` | string | Human-readable label |
| `phase` | string | Pipeline phase grouping |
| `description` | string | What the node does |
| `status` | `"pending"` \| `"running"` \| `"completed"` \| `"failed"` \| `"skipped"` | Node execution status |
| `started_at` | string \| null | ISO-8601 start timestamp |
| `completed_at` | string \| null | ISO-8601 completion timestamp |
| `duration_ms` | number \| null | Execution duration in milliseconds |
| `detail` | string \| null | Additional node-level detail |

### DocumentUploadResponse
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `uploaded` | number | Number of files processed |
| `files` | DocumentFileResult[] | Per-file OCR results (see below) |
| `structured_record` | object \| null | Merged structured record after all uploads |

### DocumentFileResult
| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | Unique document identifier |
| `original_name` | string | Uploaded filename |
| `stored_name` | string | Server-side storage filename |
| `size` | number | File size in bytes |
| `content_type` | string | MIME type |
| `path` | string | Absolute server-side file path |
| `document_type` | string | Classified document type (e.g., `lab_report`, `discharge_summary`) |
| `classification_confidence` | number | Classifier confidence score (0–1) |
| `overall_confidence` | number | Overall OCR confidence (0–100) |
| `fields_extracted` | number | Number of structured fields extracted |
| `conflicts_detected` | number | Number of conflicts found against active patient record |
| `queue_items_created` | number | Modification review queue items created |
| `processing_errors` | string[] | Non-fatal errors encountered during OCR |
| `field_changes` | object[] | Extracted field name/value pairs with confidence |
| `conflict_details` | object[] | Conflict detail records |
| `agent_summary` | string | Human-readable LLM summary of the extraction |

### ModificationQueueItemSchema
| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Unique queue item identifier |
| `session_id` | string | Owning session |
| `field_name` | string | Affected record field |
| `extracted_value` | string | Value extracted by OCR |
| `corrected_value` | string \| null | Physician-corrected value |
| `source_document` | string | Source filename |
| `confidence` | number | OCR confidence score (0–1) |
| `conflict_reason` | string | Reason the item was queued |
| `severity` | string | `"low"` \| `"medium"` \| `"high"` |
| `status` | string | `"pending"` \| `"accepted"` \| `"rejected"` \| `"modified"` |

### QueueUpdateRequest
| Field | Type | Description |
|-------|------|-------------|
| `status` | string | New status: `accepted`, `rejected`, or `modified` |
| `corrected_value` | string \| null | Physician-supplied correction (required when status is `modified`) |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| POST | `/api/session/start` | Start a new clinical session | SessionStartResponse | None |
| POST | `/api/session/{session_id}/end` | End an active session | SessionEndResponse | None |
| POST | `/api/session/{session_id}/transcribe` | Add a transcript utterance | TranscribeResponse | TranscribeRequest |
| POST | `/api/session/{session_id}/pipeline` | Run the full LangGraph pipeline | RunPipelineResponse | RunPipelineRequest |
| GET | `/api/session/{session_id}/pipeline/status` | Poll pipeline execution progress | PipelineStatusResponse | None |
| POST | `/api/session/{session_id}/upload` | Upload documents and run OCR | DocumentUploadResponse | multipart/form-data |
| GET | `/api/session/{session_id}/documents` | List documents for a session | object | None |
| GET | `/api/session/{session_id}/record` | Get the session-level structured record | object | None |
| GET | `/api/session/{session_id}/queue` | Get the modification review queue | object | None |
| PATCH | `/api/session/{session_id}/queue/{item_id}` | Accept, reject, or modify a queue item | ModificationQueueItemSchema | QueueUpdateRequest |

---

## 3. Endpoint Details

### POST `/api/session/start`

Start a new clinical session. Returns a UUID-based `session_id` that all subsequent endpoints require.

**Response**
```json
{
  "session_id": "a1b2c3d4-...",
  "message": "Session started"
}
```

---

### POST `/api/session/{session_id}/end`

End an active session. After this call the session is considered closed; further transcribe or pipeline calls against it will fail.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Active session identifier |

**Response**
```json
{
  "message": "Session ended"
}
```

---

### POST `/api/session/{session_id}/transcribe`

Append a single transcript utterance to the session. Used by the frontend VAD loop to stream speaker-labelled utterances in real time.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Active session identifier |

**Request Body** — `TranscribeRequest`
```json
{
  "text": "Patient reports chest pain for three days.",
  "speaker": "Patient"
}
```

**Response** — `TranscribeResponse`
```json
{
  "session_id": "a1b2c3d4-...",
  "speaker": "Patient",
  "transcription": "Patient reports chest pain for three days.",
  "source": "text_input",
  "agent_message": null
}
```

---

### POST `/api/session/{session_id}/pipeline`

Run the full 18-node LangGraph clinical pipeline against the provided transcript segments. This endpoint is synchronous and may take 10–60 seconds depending on transcript length and LLM latency.

Pipeline node sequence: `greeting` → `load_patient_context` → `ingest` → `clean_transcription` → `normalize_transcript` → `segment_and_chunk` → `extract_candidates` → `diagnostic_reasoning` → `retrieve_evidence` → `fill_structured_record` → `clinical_suggestions` → `validate_and_score` → (optional: `repair` / `conflict_resolution` / `human_review_gate`) → `generate_note` → `package_outputs` → `persist_results`.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Active session identifier |

**Request Body** — `RunPipelineRequest`
```json
{
  "session_id": "a1b2c3d4-...",
  "patient_id": "PAT-001",
  "doctor_id": "DR-007",
  "segments": [
    {
      "start": 0.0,
      "end": 4.2,
      "speaker": "Clinician",
      "raw_text": "How long have you had the pain?",
      "confidence": null
    }
  ],
  "is_new_patient": false
}
```

**Response** — `RunPipelineResponse`
```json
{
  "session_id": "a1b2c3d4-...",
  "clinical_note": "S: Patient presents with...",
  "structured_record": { "demographics": {}, "vitals": {}, "diagnoses": [] },
  "clinical_suggestions": { "risk_level": "low", "allergy_alerts": [] },
  "validation_report": { "needs_review": false, "schema_errors": [] },
  "message": "Pipeline completed"
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 503 | PostgreSQL / pgvector database is not available |
| 500 | Unhandled pipeline execution failure |

---

### GET `/api/session/{session_id}/pipeline/status`

Poll the real-time execution status of a running pipeline. The frontend queries this endpoint approximately every 500 ms to update the progress sidebar.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response** — `PipelineStatusResponse`
```json
{
  "session_id": "a1b2c3d4-...",
  "status": "running",
  "current_node": "extract_candidates",
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": null,
  "error": null,
  "nodes": [
    {
      "name": "ingest",
      "label": "Ingest",
      "phase": "input",
      "description": "Loads transcript segments and OCR artifacts",
      "status": "completed",
      "started_at": "2024-01-15T10:30:01Z",
      "completed_at": "2024-01-15T10:30:01.3Z",
      "duration_ms": 302.1,
      "detail": null
    }
  ]
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 404 | No pipeline record found for the given session |

---

### POST `/api/session/{session_id}/upload`

Upload one or more documents (PDF, image) and run the 9-stage OCR pipeline on each. Returns structured field extractions, conflict data, and a human-readable agent summary. Files are stored under `storage/uploads/{session_id}/`. Low-confidence fields and conflicts are automatically added to the modification review queue.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Active session identifier |

**Request** — `multipart/form-data`, field name `files` (repeatable for multiple files)

**Response** — `DocumentUploadResponse`
```json
{
  "session_id": "a1b2c3d4-...",
  "uploaded": 1,
  "files": [
    {
      "document_id": "doc-abc123",
      "original_name": "lab_results.pdf",
      "stored_name": "f8e2a1bc.pdf",
      "size": 204800,
      "content_type": "application/pdf",
      "document_type": "lab_report",
      "classification_confidence": 0.92,
      "overall_confidence": 87.4,
      "fields_extracted": 12,
      "conflicts_detected": 1,
      "queue_items_created": 2,
      "processing_errors": [],
      "field_changes": [{ "field_name": "glucose", "value": "105", "confidence": 0.95, "category": "labs" }],
      "conflict_details": [],
      "agent_summary": "Analyzed 'lab_results.pdf' — classified as Lab Report..."
    }
  ],
  "structured_record": { "labs": [], "demographics": {} }
}
```

---

### GET `/api/session/{session_id}/documents`

List all documents and their OCR results that have been uploaded for the session.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response**
```json
{
  "session_id": "a1b2c3d4-...",
  "documents": []
}
```

---

### GET `/api/session/{session_id}/record`

Return the session-level consolidated structured record. This reflects all content merged from transcription and document uploads so far, without requiring the pipeline to have run.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response**
```json
{
  "session_id": "a1b2c3d4-...",
  "structured_record": { "demographics": {}, "vitals": {}, "diagnoses": [], "medications": [] }
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 404 | Session not found or has no record yet |

---

### GET `/api/session/{session_id}/queue`

Get all pending and resolved modification review queue items for the session. Items are created when OCR detects low-confidence fields or conflicts against existing patient data.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response**
```json
{
  "session_id": "a1b2c3d4-...",
  "queue": [],
  "total": 0,
  "pending": 0
}
```

---

### PATCH `/api/session/{session_id}/queue/{item_id}`

Accept, reject, or supply a corrected value for a modification queue item. A `status` of `modified` requires a non-null `corrected_value`.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |
| `item_id` | string | Queue item identifier |

**Request Body** — `QueueUpdateRequest`
```json
{
  "status": "modified",
  "corrected_value": "108"
}
```

**Response** — Updated `ModificationQueueItemSchema` object

**Error Responses**
| Status | Description |
|--------|-------------|
| 404 | Queue item not found |
