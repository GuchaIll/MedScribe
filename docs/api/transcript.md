# Transcript API Documentation

## 1. Overview

**Base Router Path:** `/api/transcript`

This section covers the transcript processing utilities. Currently one endpoint is provided: LLM-based speaker reclassification. Given a list of transcript messages with existing speaker labels, this endpoint uses an LLM (Groq llama-3.3-70b-versatile) to reclassify each utterance as either `"Clinician"` or `"Patient"` based on clinical conversation patterns.

Requires the `GROQ_API_KEY` environment variable to be set.

---

## 1.1 Interface Definitions

### TranscriptMessage
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique message identifier |
| `speaker` | string | Current speaker label (may be overwritten by reclassification) |
| `content` | string | Utterance text |
| `timestamp` | string | ISO-8601 timestamp of the utterance |
| `type` | string | Message role: `"user"` \| `"system"` |

### ReclassifyRequest
| Field | Type | Description |
|-------|------|-------------|
| `messages` | TranscriptMessage[] | Ordered list of transcript messages to reclassify |

### ReclassifyResponse
| Field | Type | Description |
|-------|------|-------------|
| `messages` | TranscriptMessage[] | Same messages with `speaker` fields updated to `"Clinician"` or `"Patient"` |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| POST | `/api/transcript/reclassify` | Reclassify each utterance as Clinician or Patient using LLM | ReclassifyResponse | ReclassifyRequest |

---

## 3. Endpoint Details

### POST `/api/transcript/reclassify`

Use the Groq-hosted LLM to classify each transcript utterance as `"Clinician"` or `"Patient"` based on clinical conversation patterns.

Classification heuristics used by the model:
- **Clinician** — asks structured diagnostic questions, uses medical terminology, gives instructions, describes treatment plans, or orders tests
- **Patient** — describes symptoms, answers questions, expresses concerns or fears, describes daily life or prior history

All messages are sent in a single prompt to preserve conversational context. The response preserves the original message order and all non-`speaker` fields are unchanged.

When `messages` is empty, an empty list is returned immediately without calling the LLM.

**Request Body** — `ReclassifyRequest`
```json
{
  "messages": [
    {
      "id": "msg-001",
      "speaker": "Unknown",
      "content": "How long have you had the chest pain?",
      "timestamp": "2025-01-15T10:30:05Z",
      "type": "user"
    },
    {
      "id": "msg-002",
      "speaker": "Unknown",
      "content": "It started about three days ago, mostly when I breathe in.",
      "timestamp": "2025-01-15T10:30:18Z",
      "type": "user"
    },
    {
      "id": "msg-003",
      "speaker": "Unknown",
      "content": "I'm going to order a chest X-ray and an ECG.",
      "timestamp": "2025-01-15T10:31:02Z",
      "type": "user"
    }
  ]
}
```

**Response** — `ReclassifyResponse`
```json
{
  "messages": [
    {
      "id": "msg-001",
      "speaker": "Clinician",
      "content": "How long have you had the chest pain?",
      "timestamp": "2025-01-15T10:30:05Z",
      "type": "user"
    },
    {
      "id": "msg-002",
      "speaker": "Patient",
      "content": "It started about three days ago, mostly when I breathe in.",
      "timestamp": "2025-01-15T10:30:18Z",
      "type": "user"
    },
    {
      "id": "msg-003",
      "speaker": "Clinician",
      "content": "I'm going to order a chest X-ray and an ECG.",
      "timestamp": "2025-01-15T10:31:02Z",
      "type": "user"
    }
  ]
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 503 | `GROQ_API_KEY` environment variable is not set |
| 422 | LLM returned a response that could not be parsed as valid JSON |
| 500 | Groq API call or internal processing failure |
