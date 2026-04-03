# Assistant API Documentation

## 1. Overview

**Base Router Path:** `/api/session`

This section covers the AI assistant endpoint. Given an active session and a patient identifier, the assistant answers natural-language clinical questions from the physician using Retrieval-Augmented Generation (RAG). Context is pulled from the live in-memory session transcript, the incrementally built structured record, and the persisted `clinical_embeddings`, `chunk_embeddings`, and `MedicalRecord` tables.

---

## 1.1 Interface Definitions

### AssistantQueryRequest
| Field | Type | Description |
|-------|------|-------------|
| `patient_id` | string | Patient identifier for the current session |
| `question` | string | Natural-language question from the physician (minimum 3 characters) |

### AssistantQueryResponse
| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | LLM-generated answer grounded in retrieved context |
| `confidence` | number | Retrieval confidence score (0.0–1.0). Scores below 0.65 trigger a disclaimer |
| `low_confidence` | boolean | `true` when `confidence < 0.65` |
| `disclaimer` | string \| null | Shown to the physician when confidence is below the threshold |
| `sources` | object[] | Retrieval source records used to ground the answer |

### RetrievalSource
Each entry in the `sources` array describes one piece of retrieved evidence:

| Field | Type | Description |
|-------|------|-------------|
| `source_type` | string | Origin of the chunk: `"session_transcript"`, `"chunk_embedding"`, or `"medical_record"` |
| `content` | string | Retrieved text fragment |
| `score` | number | Semantic similarity score |
| `metadata` | object | Additional provenance (e.g., `session_id`, `patient_id`, `record_id`) |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| POST | `/api/session/{session_id}/assistant` | Answer a clinical question using RAG | AssistantQueryResponse | AssistantQueryRequest |

---

## 3. Endpoint Details

### POST `/api/session/{session_id}/assistant`

Answer a clinical question about a patient using Retrieval-Augmented Generation.

Retrieval sources searched in priority order:
1. Live in-memory session transcript (utterances accumulated during the current session before the pipeline persists them)
2. Live in-memory structured record (incrementally built during the session)
3. `clinical_embeddings` table — `is_final=True` finalised patient history
4. `chunk_embeddings` table — all transcript and document chunks for the patient
5. `MedicalRecord` structured data — latest finalised records

A confidence score is computed from the retrieved evidence. If confidence is below 0.65 the response includes a `disclaimer` field that the frontend must display to the physician. If no context is available, the assistant explicitly states it does not have enough information rather than hallucinating.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Active session identifier |

**Request Body** — `AssistantQueryRequest`
```json
{
  "patient_id": "PAT-001",
  "question": "What medications is this patient currently taking?"
}
```

**Response** — `AssistantQueryResponse`
```json
{
  "answer": "Based on the most recent records, the patient is currently prescribed Metformin 500mg twice daily and Lisinopril 10mg once daily.",
  "confidence": 0.82,
  "low_confidence": false,
  "disclaimer": null,
  "sources": [
    {
      "source_type": "medical_record",
      "content": "Metformin 500mg BID, Lisinopril 10mg QD",
      "score": 0.91,
      "metadata": { "record_id": "rec-xyz", "patient_id": "PAT-001" }
    }
  ]
}
```

**Low-confidence example response**
```json
{
  "answer": "The records suggest a possible history of hypertension, but the data is limited.",
  "confidence": 0.51,
  "low_confidence": true,
  "disclaimer": "This answer is based on limited or uncertain evidence. Please verify with the patient's full records.",
  "sources": []
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | Question is empty or contains only whitespace |
| 500 | LLM inference or retrieval failure |
