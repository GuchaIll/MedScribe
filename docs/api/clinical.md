# Clinical Decision Support API Documentation

## 1. Overview

**Base Router Path:** `/api/clinical`

This section covers the clinical decision support endpoints. These endpoints analyse structured medical records and medication lists for allergy conflicts, drug-drug interactions, contraindications, dosage issues, and lab result interpretation. All checks are deterministic except optional external database enrichment via RxNorm and OpenFDA. Physician overrides of alerts are logged to the HIPAA audit trail.

---

## 1.1 Interface Definitions

### ClinicalSuggestionsRequest
| Field | Type | Description |
|-------|------|-------------|
| `current_record` | object | The structured medical record being authored (StructuredRecord-compatible dict) |
| `patient_history` | object \| null | Aggregated patient history containing `allergies`, `medications`, `diagnoses`, `labs`. When omitted, only the current record is analysed |
| `use_external_database` | boolean | When `true`, enriches results with RxNorm and OpenFDA drug data. Defaults to `false` |

### ClinicalSuggestionsResponse
| Field | Type | Description |
|-------|------|-------------|
| `risk_level` | string | Overall risk assessment: `"low"` \| `"moderate"` \| `"high"` \| `"critical"` |
| `allergy_alerts` | object[] | Allergy-medication conflict alerts |
| `drug_interactions` | object[] | Drug-drug interaction alerts |
| `contraindications` | object[] | Diagnosis-based contraindication alerts |
| `dosage_issues` | object[] | Dosage appropriateness flags |
| `context_notes` | object[] | Informational notes from prior visit history |

### AllergyCheckRequest
| Field | Type | Description |
|-------|------|-------------|
| `medications` | object[] | List of medication dicts, each with at least a `name` field |
| `allergies` | object[] | List of allergy dicts with `substance` and `reaction` fields |

### AllergyCheckResponse
| Field | Type | Description |
|-------|------|-------------|
| `allergy_alerts` | object[] | Detected allergy-medication conflicts |
| `risk_level` | string | `"low"` \| `"moderate"` \| `"high"` \| `"critical"` |

### InteractionCheckRequest
| Field | Type | Description |
|-------|------|-------------|
| `medications` | object[] | List of medication dicts, each with at least a `name` field |

### InteractionCheckResponse
| Field | Type | Description |
|-------|------|-------------|
| `drug_interactions` | object[] | Detected drug-drug interactions |
| `risk_level` | string | `"low"` \| `"moderate"` \| `"high"` \| `"critical"` |

### LabInterpretationRequest
| Field | Type | Description |
|-------|------|-------------|
| `labs` | object[] | Lab results, each with `test_name`, `value`, and `unit` fields |
| `patient_context` | object \| null | Optional patient demographics for contextual interpretation: `age`, `sex`, `conditions` |

### LabInterpretationResponse
| Field | Type | Description |
|-------|------|-------------|
| `interpretations` | object[] | Per-test interpretation with reference ranges, severity, and clinical significance |
| `risk_flags` | string[] | Critical value flags that require immediate attention |
| `summary` | string | Narrative summary of overall lab findings |

### ClinicalOverrideRequest
| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session the alert occurred in |
| `alert_type` | string | `"allergy_conflict"` \| `"drug_interaction"` \| `"contraindication"` \| `"dosage_issue"` |
| `alert_summary` | string | Brief description of the alert being overridden |
| `justification` | string | Clinical justification for the override (required) |
| `overridden_by` | string | Physician or user identifier |

### ClinicalOverrideResponse
| Field | Type | Description |
|-------|------|-------------|
| `override_id` | integer | Database ID of the audit log entry, or `-1` on in-memory fallback |
| `message` | string | Confirmation message |
| `logged` | boolean | `true` if the override was persisted (DB or in-memory fallback) |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| POST | `/api/clinical/suggestions` | Generate clinical decision support suggestions for a structured record | ClinicalSuggestionsResponse | ClinicalSuggestionsRequest |
| POST | `/api/clinical/check-allergies` | Quick allergy-vs-medication conflict check | AllergyCheckResponse | AllergyCheckRequest |
| POST | `/api/clinical/check-interactions` | Quick drug-drug interaction check | InteractionCheckResponse | InteractionCheckRequest |
| POST | `/api/clinical/interpret-labs` | Interpret lab results with clinical context | LabInterpretationResponse | LabInterpretationRequest |
| POST | `/api/clinical/override` | Log a physician override of a clinical alert | ClinicalOverrideResponse | ClinicalOverrideRequest |

---

## 3. Endpoint Details

### POST `/api/clinical/suggestions`

Generate a full clinical decision support analysis for a structured medical record.

Checks performed:
- Allergy-medication conflicts (substance vs. medication name matching)
- Drug-drug interactions (known interaction database lookup)
- Contraindications based on diagnoses and conditions
- Dosage appropriateness (age, weight, renal function where available)
- Historical context from prior visit data when `patient_history` is provided

When `use_external_database` is `true`, medication data is enriched via RxNorm and OpenFDA, providing standardised drug names and known interaction data.

**Request Body** — `ClinicalSuggestionsRequest`
```json
{
  "current_record": {
    "medications": [
      { "name": "Penicillin V", "dose": "500mg", "frequency": "QID" }
    ],
    "diagnoses": [{ "code": "J18.9", "description": "Pneumonia" }],
    "allergies": [{ "substance": "Penicillin", "reaction": "anaphylaxis" }]
  },
  "patient_history": null,
  "use_external_database": false
}
```

**Response** — `ClinicalSuggestionsResponse`
```json
{
  "risk_level": "critical",
  "allergy_alerts": [
    {
      "medication": "Penicillin V",
      "allergen": "Penicillin",
      "reaction": "anaphylaxis",
      "severity": "critical",
      "recommendation": "Contraindicated — patient has a documented anaphylactic reaction to Penicillin"
    }
  ],
  "drug_interactions": [],
  "contraindications": [],
  "dosage_issues": [],
  "context_notes": []
}
```

---

### POST `/api/clinical/check-allergies`

Lightweight allergy-vs-medication conflict check. Does not require a full structured record or patient history. Intended for point-of-care use when adding a new medication.

**Request Body** — `AllergyCheckRequest`
```json
{
  "medications": [
    { "name": "Amoxicillin", "dose": "250mg" }
  ],
  "allergies": [
    { "substance": "Penicillin", "reaction": "rash" }
  ]
}
```

**Response** — `AllergyCheckResponse`
```json
{
  "allergy_alerts": [
    {
      "medication": "Amoxicillin",
      "allergen": "Penicillin",
      "reaction": "rash",
      "severity": "high",
      "recommendation": "Caution — cross-reactivity risk between Amoxicillin and Penicillin"
    }
  ],
  "risk_level": "high"
}
```

---

### POST `/api/clinical/check-interactions`

Quick drug-drug interaction check for a list of medications. Does not require patient history.

**Request Body** — `InteractionCheckRequest`
```json
{
  "medications": [
    { "name": "Warfarin", "dose": "5mg" },
    { "name": "Aspirin", "dose": "81mg" }
  ]
}
```

**Response** — `InteractionCheckResponse`
```json
{
  "drug_interactions": [
    {
      "drug_a": "Warfarin",
      "drug_b": "Aspirin",
      "severity": "high",
      "description": "Concurrent use increases bleeding risk",
      "recommendation": "Monitor INR closely; consider alternative antiplatelet therapy"
    }
  ],
  "risk_level": "high"
}
```

---

### POST `/api/clinical/interpret-labs`

Interpret lab results against reference ranges with optional patient-context-adjusted thresholds. Returns per-test interpretation, clinical significance, and any critical value flags.

**Request Body** — `LabInterpretationRequest`
```json
{
  "labs": [
    { "test_name": "Hemoglobin", "value": "7.2", "unit": "g/dL" },
    { "test_name": "Creatinine", "value": "3.1", "unit": "mg/dL" }
  ],
  "patient_context": {
    "age": 72,
    "sex": "female",
    "conditions": ["chronic kidney disease"]
  }
}
```

**Response** — `LabInterpretationResponse`
```json
{
  "interpretations": [
    {
      "test_name": "Hemoglobin",
      "value": "7.2",
      "unit": "g/dL",
      "reference_range": "12.0–16.0 g/dL",
      "status": "critical",
      "severity": "critical",
      "clinical_significance": "Severe anaemia. Immediate evaluation warranted."
    },
    {
      "test_name": "Creatinine",
      "value": "3.1",
      "unit": "mg/dL",
      "reference_range": "0.5–1.1 mg/dL",
      "status": "critical",
      "severity": "high",
      "clinical_significance": "Markedly elevated creatinine consistent with advanced CKD stage."
    }
  ],
  "risk_flags": ["Hemoglobin critically low", "Creatinine markedly elevated"],
  "summary": "Two critical lab findings identified. Immediate clinical review recommended."
}
```

---

### POST `/api/clinical/override`

Log a physician's override of a clinical decision support alert. The override is written to the HIPAA audit log (`AuditLog` table). A non-empty clinical justification is mandatory.

When the database is unavailable, the override falls back to an in-memory log entry and `logged` is still returned as `true`.

**Request Body** — `ClinicalOverrideRequest`
```json
{
  "session_id": "a1b2c3d4-...",
  "alert_type": "allergy_conflict",
  "alert_summary": "Penicillin V prescribed despite documented Penicillin allergy",
  "justification": "Patient allergy is documented as a mild rash. Anaphylaxis risk is low. No suitable alternative for this infection.",
  "overridden_by": "DR-007"
}
```

**Response** — `ClinicalOverrideResponse`
```json
{
  "override_id": 42,
  "message": "Override logged successfully",
  "logged": true
}
```

**Error Responses**
| Status | Description |
|--------|-------------|
| 400 | `justification` is empty or contains only whitespace |
| 500 | Unexpected server error during audit log write |
