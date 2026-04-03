# Patient API Documentation

## 1. Overview

**Base Router Path:** `/api/patient`

This section covers the longitudinal patient view endpoints. These endpoints aggregate data across all historical medical records for a patient to produce trend analyses, composite risk scores, and a unified patient profile. Data is sourced from the PostgreSQL `Patient` and `MedicalRecord` tables. All endpoints degrade gracefully when the database is unavailable, returning empty structures rather than an error.

---

## 1.1 Interface Definitions

### PatientInfo
| Field | Type | Description |
|-------|------|-------------|
| `patient_id` | string | Patient identifier |
| `mrn` | string | Medical Record Number |
| `full_name` | string | Patient full name |
| `dob` | string \| null | Date of birth (ISO-8601 date string) |
| `age` | integer \| null | Age in years |
| `sex` | string \| null | Biological sex |

### LabTrend
| Field | Type | Description |
|-------|------|-------------|
| `test_name` | string | Lab test name (e.g., `"Hemoglobin"`, `"Creatinine"`) |
| `data_points` | object[] | Time-series data points with `value`, `unit`, and `date` fields |
| `trend_direction` | string | `"improving"` \| `"worsening"` \| `"stable"` \| `"fluctuating"` |
| `latest_value` | string \| null | Most recent recorded value with unit |
| `latest_status` | string | `"normal"` \| `"borderline"` \| `"abnormal"` \| `"critical"` |

### RiskScore
| Field | Type | Description |
|-------|------|-------------|
| `overall` | string | Composite risk level: `"low"` \| `"moderate"` \| `"high"` \| `"critical"` |
| `score` | number | Numeric risk score (higher is worse) |
| `factors` | object[] | Contributing risk factors with individual weights |
| `recommendations` | string[] | Actionable recommendations based on risk factors |

### PatientProfileResponse
| Field | Type | Description |
|-------|------|-------------|
| `patient_id` | string | Patient identifier |
| `patient_info` | PatientInfo | Demographic information |
| `lab_trends` | LabTrend[] | Trend analysis for all recorded lab tests |
| `medication_timeline` | object[] | Chronological medication history across visits |
| `risk_score` | RiskScore \| null | Current composite risk score |
| `visit_count` | integer | Total number of recorded visits |

---

## 2. REST API Endpoints

| Method | Path | Function | Success Response Type | Body Type |
|--------|------|----------|-----------------------|-----------|
| GET | `/api/patient/{patient_id}/profile` | Full longitudinal profile with lab trends, medication timeline, and risk score | PatientProfileResponse | None |
| GET | `/api/patient/{patient_id}/lab-trends` | Lab value trend analysis, optionally filtered by test name | object | None |
| GET | `/api/patient/{patient_id}/risk-score` | Current composite risk score | object | None |

---

## 3. Endpoint Details

### GET `/api/patient/{patient_id}/profile`

Build a full longitudinal profile for a patient. Aggregates lab trends, medication timeline, and composite risk score across all historical `MedicalRecord` entries (up to the 50 most recent records). Returns an empty structure if no records are found or the database is unavailable.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `patient_id` | string | Patient identifier |

**Response** — `PatientProfileResponse`
```json
{
  "patient_id": "PAT-001",
  "patient_info": {
    "patient_id": "PAT-001",
    "mrn": "MRN-123456",
    "full_name": "Jane Doe",
    "dob": "1952-03-14",
    "age": 72,
    "sex": "female"
  },
  "lab_trends": [
    {
      "test_name": "Hemoglobin",
      "data_points": [
        { "value": "11.2", "unit": "g/dL", "date": "2024-10-01" },
        { "value": "10.8", "unit": "g/dL", "date": "2025-01-15" }
      ],
      "trend_direction": "worsening",
      "latest_value": "10.8 g/dL",
      "latest_status": "abnormal"
    }
  ],
  "medication_timeline": [
    { "name": "Metformin", "dose": "500mg", "frequency": "BID", "start_date": "2022-06-01", "end_date": null }
  ],
  "risk_score": {
    "overall": "moderate",
    "score": 42,
    "factors": [
      { "name": "Anaemia", "weight": 15 },
      { "name": "Type 2 Diabetes", "weight": 20 }
    ],
    "recommendations": [
      "Monitor haemoglobin every 3 months",
      "Review HbA1c at next visit"
    ]
  },
  "visit_count": 8
}
```

---

### GET `/api/patient/{patient_id}/lab-trends`

Return lab trend analysis for a patient. Flattens all lab entries from all historical records and computes per-test trend direction, most recent value, and status. Optionally filter to a single test by providing `test_name` as a query parameter (case-insensitive).

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `patient_id` | string | Patient identifier |

**Query Parameters**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `test_name` | string | No | Filter results to a single lab test (e.g., `Creatinine`) |

**Response**
```json
{
  "patient_id": "PAT-001",
  "trends": [
    {
      "test_name": "Creatinine",
      "data_points": [
        { "value": "1.1", "unit": "mg/dL", "date": "2023-05-10" },
        { "value": "1.4", "unit": "mg/dL", "date": "2024-02-20" },
        { "value": "3.1", "unit": "mg/dL", "date": "2025-01-15" }
      ],
      "trend_direction": "worsening",
      "latest_value": "3.1 mg/dL",
      "latest_status": "critical"
    }
  ]
}
```

---

### GET `/api/patient/{patient_id}/risk-score`

Compute the current composite risk score for a patient by aggregating all diagnoses, medications, and lab results from historical records. The score is derived from a deterministic rule-based model that weights known clinical risk factors.

**Path Parameters**
| Name | Type | Description |
|------|------|-------------|
| `patient_id` | string | Patient identifier |

**Response**
```json
{
  "patient_id": "PAT-001",
  "risk": {
    "overall": "high",
    "score": 71,
    "factors": [
      { "name": "Chronic Kidney Disease", "weight": 25 },
      { "name": "Anaemia", "weight": 15 },
      { "name": "Hypertension", "weight": 18 },
      { "name": "Type 2 Diabetes", "weight": 13 }
    ],
    "recommendations": [
      "Nephrology referral recommended",
      "Optimise blood pressure control",
      "Monitor HbA1c quarterly"
    ]
  }
}
```
