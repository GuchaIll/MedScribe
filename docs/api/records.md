# Records API Documentation

## 1. Overview

**Base Router Path:** `/api/records`

This section covers the medical record generation, preview, feedback-driven regeneration, finalisation, and version history endpoints. Records are rendered from a structured `StructuredRecord` dict using one of four Jinja2-backed templates. The commit endpoint marks a record as final in PostgreSQL and writes a HIPAA audit trail entry.

---

## 1.1 Interface Definitions

### TemplateInfo
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Template identifier used in requests |
| `description` | string | Human-readable template description |
| `formats` | string[] | Supported output formats for this template |

Available templates:

| Name | Description |
|------|-------------|
| `soap` | SOAP Note — Subjective, Objective, Assessment, Plan |
| `discharge` | Discharge Summary — inpatient discharge documentation |
| `consultation` | Consultation Note — specialist referral documentation |
| `progress` | Progress Note — follow-up visit documentation |

### GenerateRecordRequest
| Field | Type | Description |
|-------|------|-------------|
| `record` | object | Structured medical record (StructuredRecord-compatible dict) |
| `template` | string | Template name: `soap` \| `discharge` \| `consultation` \| `progress`. Defaults to `soap` |
| `clinical_suggestions` | object \| null | Optional clinical suggestions to embed as an alert panel in the record |
| `format` | string | Output format: `html` \| `pdf` \| `text`. Defaults to `html` |

### RegenerateRecordRequest
| Field | Type | Description |
|-------|------|-------------|
| `record` | object | Current structured medical record dict |
| `template` | string | Template name. Defaults to `soap` |
| `clinical_suggestions` | object \| null | Optional clinical suggestions |
| `feedback` | string | Physician feedback or corrections to incorporate |
| `format` | string | Output format: `html` \| `pdf` \| `text`. Defaults to `html` |
| `iteration` | integer | Regeneration attempt number (returned incremented in the response) |

### RegenerateRecordResponse
| Field | Type | Description |
|-------|------|-------------|
| `html` | string | Rendered HTML (when format is `html`) |
| `updated_record` | object | Updated structured record after applying feedback |
| `iteration` | integer | `iteration + 1` — the next attempt number |
| `feedback_applied` | string | Echo of the feedback that was applied |

### RecordCommitRequest
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session the record belongs to |
| `record_id` | string | Record identifier to finalise |
| `corrections` | object \| null | Optional field corrections to merge before finalising |
| `template` | string | Template used. Defaults to `soap` |
| `finalized_by` | string | Physician or user identifier |

### RecordCommitResponse
| Field | Type | Description |
|-------|------|-------------|
| `record_id` | string | Record identifier |
| `version` | integer | Final version number |
| `is_final` | boolean | Always `true` after a successful commit |
| `message` | string | Confirmation message |

### RecordVersionSchema
| Field | Type | Description |
|-------|------|-------------|
| `record_id` | string | Record identifier |
| `session_id` | string | Owning session |
| `version` | integer | Version number |
| `is_final` | boolean | Whether the record has been finalised |
| `confidence_score` | integer \| null | Pipeline confidence score at time of creation |
| `record_type` | string \| null | Template type used (e.g., `SOAP`) |
| `created_by` | string | Creator identifier |
| `created_at` | string | ISO-8601 creation timestamp |
| `finalized_at` | string \| null | ISO-8601 finalisation timestamp |
| `finalized_by` | string \| null | Identifier of the physician who finalised the record |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| GET | `/api/records/templates` | List available record templates | TemplateInfo[] | None |
| POST | `/api/records/generate` | Generate a formatted medical record | HTML / PDF bytes / plain text | GenerateRecordRequest |
| POST | `/api/records/preview` | Generate a browser-ready HTML preview | HTML | GenerateRecordRequest |
| POST | `/api/records/regenerate` | Regenerate a record incorporating physician feedback | RegenerateRecordResponse | RegenerateRecordRequest |
| POST | `/api/records/commit` | Finalise a physician-reviewed record | RecordCommitResponse | RecordCommitRequest |
| GET | `/api/records/patient/{patient_id}/history` | List record version history for a patient | object | None |

---

## 3. Endpoint Details

### GET `/api/records/templates`

List all available record templates and the output formats each supports.

**Response** — `TemplateInfo[]`
```json
[
  {
    "name": "soap",
    "description": "SOAP Note — Subjective, Objective, Assessment, Plan",
    "formats": ["html", "pdf", "text"]
  },
  {
    "name": "discharge",
    "description": "Discharge Summary — inpatient discharge documentation",
    "formats": ["html", "pdf", "text"]
  },
  {
    "name": "consultation",
    "description": "Consultation Note — specialist referral documentation",
    "formats": ["html", "pdf", "text"]
  },
  {
    "name": "progress",
    "description": "Progress Note — follow-up visit documentation",
    "formats": ["html", "pdf", "text"]
  }
]
```

---

### POST `/api/records/generate`

Generate a formatted medical record from a structured data dict. Returns HTML, PDF bytes, or plain text depending on the `format` field.

PDF generation requires WeasyPrint to be installed. When WeasyPrint is not available, the endpoint falls back to returning HTML with `Content-Type: text/html` even if `pdf` was requested.

**Request Body** — `GenerateRecordRequest`
```json
{
  "record": {
    "demographics": { "full_name": "Jane Doe", "dob": "1952-03-14" },
    "vitals": { "blood_pressure": "140/90", "heart_rate": "78" },
    "diagnoses": [{ "code": "I10", "description": "Essential hypertension" }],
    "medications": [{ "name": "Lisinopril", "dose": "10mg", "frequency": "QD" }],
    "plan": "Continue current antihypertensive therapy. Follow up in 3 months."
  },
  "template": "soap",
  "clinical_suggestions": null,
  "format": "html"
}
```

**Response**
- `format=html` — `text/html` HTML document
- `format=pdf` — `application/pdf` binary (falls back to `text/html` if WeasyPrint unavailable)
- `format=text` — `text/plain` plain-text record

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | Unknown template name |
| 400 | Unknown output format |

---

### POST `/api/records/preview`

Generate a browser-friendly HTML preview of a record. Equivalent to `POST /generate` with `format=html` but always returns an HTML response regardless of the `format` field. Intended for rendering inside an iframe or browser tab.

**Request Body** — `GenerateRecordRequest` (same as `/generate`)

**Response** — `text/html` HTML document

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | Unknown template name |

---

### POST `/api/records/regenerate`

Regenerate a medical record incorporating physician feedback. The endpoint uses the LLM to apply the physician's corrections to the structured record dict, preserving the original schema, then renders the updated record via the specified template. Returns the new rendered output along with the updated structured dict and the next iteration number.

If the LLM is unavailable, the original record is returned unchanged.

**Request Body** — `RegenerateRecordRequest`
```json
{
  "record": {
    "diagnoses": [{ "code": "I10", "description": "Hypertension" }],
    "plan": "Monitor blood pressure weekly."
  },
  "template": "soap",
  "clinical_suggestions": null,
  "feedback": "Add a note that the patient also has stage 3 CKD and adjust the plan to include nephrology referral.",
  "format": "html",
  "iteration": 1
}
```

**Response** — `RegenerateRecordResponse`
```json
{
  "html": "<!DOCTYPE html>...",
  "updated_record": {
    "diagnoses": [
      { "code": "I10", "description": "Hypertension" },
      { "code": "N18.3", "description": "Chronic kidney disease, stage 3" }
    ],
    "plan": "Monitor blood pressure weekly. Refer to nephrology for CKD management."
  },
  "iteration": 2,
  "feedback_applied": "Add a note that the patient also has stage 3 CKD and adjust the plan to include nephrology referral."
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | Unknown template name or output format |

---

### POST `/api/records/commit`

Finalise a physician-reviewed medical record. Sets `is_final=True` on the `MedicalRecord` row, increments the version number if corrections are provided, records the finalisation timestamp and author, and writes a HIPAA audit log entry.

If the record does not exist in the database (e.g., the pipeline ran in-memory without database persistence), a minimal record is created before finalisation.

**Request Body** — `RecordCommitRequest`
```json
{
  "session_id": "a1b2c3d4-...",
  "record_id": "rec-xyz789",
  "corrections": {
    "plan": "Updated plan: continue Lisinopril and recheck BP in 6 weeks."
  },
  "template": "soap",
  "finalized_by": "DR-007"
}
```

**Response** — `RecordCommitResponse`
```json
{
  "record_id": "rec-xyz789",
  "version": 2,
  "is_final": true,
  "message": "Record finalized as version 2"
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 503 | Database not available |
| 500 | Unexpected error during commit |

---

### GET `/api/records/patient/{patient_id}/history`

Return all medical record versions for a patient, ordered newest first. Each entry is a summary of the record version metadata without the full structured data. Useful for longitudinal review and audit.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `patient_id` | string | Patient identifier |

**Query Parameters**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `limit` | integer | No | `20` | Maximum number of records to return (max 100) |

**Response**
```json
{
  "patient_id": "PAT-001",
  "total": 3,
  "records": [
    {
      "record_id": "rec-xyz789",
      "session_id": "a1b2c3d4-...",
      "version": 2,
      "is_final": true,
      "confidence_score": 88,
      "record_type": "SOAP",
      "created_by": "DR-007",
      "created_at": "2025-01-15T10:45:00Z",
      "finalized_at": "2025-01-15T11:02:30Z",
      "finalized_by": "DR-007"
    }
  ]
}
```
