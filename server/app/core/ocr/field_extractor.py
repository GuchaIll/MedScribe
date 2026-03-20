"""
Structured field extraction from OCR text using LLM.

Combines medical NLP entity extraction (Stage 6) with
LLM-based structured extraction (Stage 7) from the pipeline.

Extracts: medications, allergies, diagnoses, lab values,
demographics, procedures, vital signs, and physician notes.

Each field includes confidence scoring and source provenance.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .document_classifier import DocumentType

logger = logging.getLogger(__name__)


class FieldCategory(str, Enum):
    """Categories of extracted clinical fields."""
    MEDICATION = "medication"
    ALLERGY = "allergy"
    DIAGNOSIS = "diagnosis"
    LAB_RESULT = "lab_result"
    VITAL_SIGN = "vital_sign"
    PROCEDURE = "procedure"
    DEMOGRAPHIC = "demographic"
    PHYSICIAN_NOTE = "physician_note"
    FOLLOW_UP = "follow_up"
    INSURANCE = "insurance"


@dataclass
class ExtractedField:
    """A single structured field extracted from a document."""
    field_id: str = ""
    field_name: str = ""
    value: Any = ""
    category: FieldCategory = FieldCategory.PHYSICIAN_NOTE
    confidence: float = 0.0
    source_document: str = ""
    source_span: str = ""
    extraction_method: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.field_id:
            self.field_id = f"fld_{uuid.uuid4().hex[:12]}"


def extract_fields(
    text: str,
    *,
    doc_type: DocumentType = DocumentType.UNKNOWN,
    ocr_confidence: float = 1.0,
    source_document: str = "",
    use_llm: bool = True,
) -> List[ExtractedField]:
    """
    Extract structured medical fields from document text.

    Runs LLM-based extraction with document-type-specific prompts
    and falls back to regex-based extraction if LLM is unavailable.

    Parameters
    ----------
    text : str
        Normalized OCR text from the document.
    doc_type : DocumentType
        Classified document type (used for targeted prompts).
    ocr_confidence : float
        OCR confidence (0-1); used to scale field confidence.
    source_document : str
        Filename/identifier of the source document.
    use_llm : bool
        Whether to use Groq LLM for extraction.

    Returns
    -------
    List[ExtractedField]
    """
    if not text or not text.strip():
        return []

    fields: List[ExtractedField] = []

    if use_llm:
        llm_fields = _extract_via_llm(text, doc_type=doc_type, source_document=source_document)
        if llm_fields:
            # Scale confidence by OCR confidence
            for f in llm_fields:
                f.confidence = round(f.confidence * ocr_confidence, 2)
            fields.extend(llm_fields)

    # Always run regex extraction to catch what LLM might miss
    regex_fields = _extract_via_regex(text, source_document=source_document)

    # Merge: add regex fields that aren't already covered by LLM
    if fields:
        existing_keys = {
            (f.category, f.field_name.lower(), str(f.value).lower()[:50])
            for f in fields
        }
        for rf in regex_fields:
            key = (rf.category, rf.field_name.lower(), str(rf.value).lower()[:50])
            if key not in existing_keys:
                rf.confidence = round(rf.confidence * ocr_confidence, 2)
                fields.append(rf)
    else:
        # LLM failed — use only regex
        for rf in regex_fields:
            rf.confidence = round(rf.confidence * ocr_confidence, 2)
        fields = regex_fields

    return fields


# ── LLM-based extraction ───────────────────────────────────────────────────

# Document-type-specific extraction hints
_EXTRACTION_HINTS: Dict[DocumentType, str] = {
    DocumentType.LAB_REPORT: (
        "Focus on: test names, values, units, reference ranges, "
        "dates, ordering physician. Flag any abnormal values."
    ),
    DocumentType.PRESCRIPTION: (
        "Focus on: drug name, dosage, frequency, route, quantity, "
        "refills, prescribing physician, date."
    ),
    DocumentType.DISCHARGE_SUMMARY: (
        "Focus on: admission/discharge dates, admitting diagnosis, "
        "discharge diagnosis, hospital course, discharge medications, "
        "follow-up instructions."
    ),
    DocumentType.RADIOLOGY_REPORT: (
        "Focus on: modality, body part, findings, impression, "
        "comparison studies, referring physician, date."
    ),
    DocumentType.MEDICAL_HISTORY: (
        "Focus on: chronic conditions, past surgeries, family history, "
        "social history, current medications, known allergies."
    ),
    DocumentType.INTAKE_FORM: (
        "Focus on: patient demographics (name, DOB, sex, address, phone), "
        "insurance info, emergency contact, chief complaint, "
        "current medications, allergies."
    ),
}


def _extract_via_llm(
    text: str,
    *,
    doc_type: DocumentType = DocumentType.UNKNOWN,
    source_document: str = "",
) -> Optional[List[ExtractedField]]:
    """Use Groq LLM for structured medical field extraction."""
    try:
        from groq import Groq
    except ImportError:
        return None

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    # Truncate to fit in context window
    sample = text[:6000]
    hint = _EXTRACTION_HINTS.get(doc_type, "Extract all medical information.")
    categories = [c.value for c in FieldCategory]

    prompt = f"""Extract all structured medical data from this clinical document.

Document type: {doc_type.value}
Extraction focus: {hint}

Return a JSON array. Each element must have:
- "field_name": snake_case name
- "value": extracted value (string, number, or nested object)
- "category": one of {json.dumps(categories)}
- "confidence": 0.0–1.0
- "source_span": exact verbatim text fragment (max 120 chars)
- "metadata": additional context object

MANDATORY — extract ALL of the following when present:

DEMOGRAPHICS (field_name examples):
  patient_name, date_of_birth, sex, mrn, phone, email, address,
  insurance_provider, insurance_policy_number, emergency_contact_name

CHIEF COMPLAINT:
  chief_complaint — value: {{free_text, onset, duration, severity, location}}

HPI (one object per symptom):
  hpi_event — value: {{symptom, onset, progression, triggers, relieving_factors,
                        associated_symptoms, timeline}}

PAST MEDICAL HISTORY:
  chronic_condition — value: {{name, icd10_code, onset_year, status}}
    *** CRITICAL: extract EVERY chronic disease listed: hypertension, diabetes,
        obesity, hyperlipidemia, COPD, asthma, CAD, CKD, hypothyroidism, etc. ***
  surgery — value: {{name, date}}
  hospitalization — value: {{reason, date, duration}}

MEDICATIONS (extract EVERY drug):
  medication — value: {{name, dose, route, frequency, indication}}
  *** Include OTC drugs, supplements, inhalers, patches, injections ***

ALLERGIES (safety-critical — extract ALL):
  allergy — value: {{substance, reaction, severity, category}}

FAMILY HISTORY:
  family_history — value: {{member, conditions: [...], alive, cause_of_death}}

SOCIAL HISTORY:
  social_history — value: {{tobacco, alcohol, drug_use, occupation, exercise, diet}}

REVIEW OF SYSTEMS (one entry per system):
  ros_finding — value: {{system, finding}}

VITALS (one entry per measurement):
  vital — value: {{type, value, unit}}
  *** heart_rate, respiratory_rate, temperature, spo2 are REQUIRED if present ***

LABS (comprehensive — include ALL results):
  lab_result — value: {{test, value, unit, reference_range, abnormal, date}}
  *** LDL, triglycerides, LFTs, CBC, CMP components, vitamin D, B12, PSA, etc. ***

PHYSICAL EXAM:
  physical_exam_finding — value: {{system, finding}}

PROBLEM LIST:
  problem — value: {{name, status}}

ASSESSMENT & PLAN:
  assessment — value: {{likely_diagnoses: [...], differential_diagnoses: [...],
                         clinical_reasoning}}
  plan — value: {{medications_prescribed: [...], tests_ordered: [...],
                   lifestyle_recommendations: [...], follow_up, referrals: [...]}}

Post-extraction rules:
- Deduplicate: if the same entity appears twice with different detail, merge into one entry with the richer data
- Normalize units: convert all heights to cm, weights to kg if both forms present; use canonical lab units (mg/dL, mmol/L, etc.)
- Do NOT include noise tokens (single words, punctuation fragments, non-medical text)
- Return ONLY a JSON array, no prose

Document text:
---
{sample}
---"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical document data extractor. "
                        "Return only valid JSON arrays. "
                        "Be thorough — extract every clinical entity."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=3000,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        items = json.loads(raw)
        if not isinstance(items, list):
            items = [items]

        fields = []
        for item in items:
            try:
                cat_str = item.get("category", "physician_note")
                try:
                    category = FieldCategory(cat_str)
                except ValueError:
                    category = FieldCategory.PHYSICIAN_NOTE

                fields.append(ExtractedField(
                    field_name=str(item.get("field_name", "")),
                    value=item.get("value", ""),
                    category=category,
                    confidence=min(max(float(item.get("confidence", 0.5)), 0.0), 1.0),
                    source_document=source_document,
                    source_span=str(item.get("source_span", ""))[:200],
                    extraction_method="llm_groq",
                    metadata=item.get("metadata", {}),
                ))
            except Exception as e:
                logger.debug("Skipping malformed field: %s", e)
                continue

        return fields if fields else None

    except Exception as e:
        logger.warning("LLM field extraction failed: %s", e)
        return None


# ── Regex-based fallback extraction ─────────────────────────────────────────

def _extract_via_regex(
    text: str,
    *,
    source_document: str = "",
) -> List[ExtractedField]:
    """Regex-based medical entity extraction as fallback."""
    fields: List[ExtractedField] = []

    # Demographics
    fields.extend(_extract_demographics(text, source_document))
    # Medications
    fields.extend(_extract_medications(text, source_document))
    # Allergies
    fields.extend(_extract_allergies(text, source_document))
    # Lab values
    fields.extend(_extract_lab_values(text, source_document))
    # Vital signs
    fields.extend(_extract_vitals(text, source_document))
    # Diagnoses
    fields.extend(_extract_diagnoses(text, source_document))

    return fields


def _extract_demographics(text: str, source: str) -> List[ExtractedField]:
    """Extract patient demographic information."""
    fields = []
    patterns = {
        "patient_name": [
            r"(?:patient\s*(?:name)?|name)\s*[:\-]\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})",
            r"(?:Mr\.|Mrs\.|Ms\.|Dr\.)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,2})",
        ],
        "date_of_birth": [
            r"(?:D\.?O\.?B\.?|date\s+of\s+birth|birth\s*date)\s*[:\-]\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        ],
        "mrn": [
            r"(?:MRN|medical\s+record\s+(?:number|no\.?))\s*[:\-]?\s*(\w{4,20})",
        ],
        "sex": [
            r"(?:sex|gender)\s*[:\-]\s*(male|female|M|F)\b",
        ],
        "age": [
            r"(?:age)\s*[:\-]\s*(\d{1,3})\s*(?:years?|y/?o)?",
        ],
    }

    for field_name, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.append(ExtractedField(
                    field_name=field_name,
                    value=match.group(1).strip(),
                    category=FieldCategory.DEMOGRAPHIC,
                    confidence=0.6,
                    source_document=source,
                    source_span=match.group(0)[:100],
                    extraction_method="regex",
                ))
                break  # Take first match per field
    return fields


def _extract_medications(text: str, source: str) -> List[ExtractedField]:
    """Extract medication mentions with dosage."""
    fields = []
    # Pattern: Drug Name + optional dosage
    med_pattern = re.compile(
        r"\b([A-Z][a-z]+(?:in|ol|am|il|ne|an|ide|ate|one|ine|fen|pam|lam|pin|vir|mab)\b)"
        r"(?:\s+(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?|IU)))?",
        re.IGNORECASE,
    )
    seen = set()
    for match in med_pattern.finditer(text):
        drug_name = match.group(1).strip()
        dosage = match.group(2).strip() if match.group(2) else ""
        key = drug_name.lower()
        if key not in seen and len(drug_name) > 3:
            seen.add(key)
            fields.append(ExtractedField(
                field_name=drug_name.lower(),
                value=f"{drug_name} {dosage}".strip(),
                category=FieldCategory.MEDICATION,
                confidence=0.5,
                source_document=source,
                source_span=match.group(0)[:100],
                extraction_method="regex",
                metadata={"dose": dosage} if dosage else {},
            ))
    return fields[:30]  # Cap to avoid noise


def _extract_allergies(text: str, source: str) -> List[ExtractedField]:
    """Extract allergy mentions."""
    fields = []
    patterns = [
        r"(?:allergic\s+to|allergy\s+to|allergies?\s*[:\-]\s*)([^\n,;\.]{3,50})",
        r"(?:known\s+allergies?\s*[:\-]\s*)([^\n\.]{3,100})",
    ]
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            substance = match.group(1).strip()
            # Split on commas for multiple allergies
            for item in re.split(r"[,;]", substance):
                item = item.strip()
                if item and item.lower() not in seen and len(item) > 2:
                    seen.add(item.lower())
                    fields.append(ExtractedField(
                        field_name=item.lower(),
                        value=item,
                        category=FieldCategory.ALLERGY,
                        confidence=0.55,
                        source_document=source,
                        source_span=match.group(0)[:100],
                        extraction_method="regex",
                    ))
    return fields


def _extract_lab_values(text: str, source: str) -> List[ExtractedField]:
    """Extract lab test results with values and units."""
    fields = []
    # Common lab tests with value patterns
    lab_pattern = re.compile(
        r"(?P<test>(?:hemoglobin|hgb|hematocrit|hct|wbc|rbc|platelets?|glucose|"
        r"creatinine|bun|sodium|potassium|chloride|co2|calcium|albumin|"
        r"bilirubin|ast|alt|alp|gfr|hba1c|tsh|t3|t4|inr|ptt|pt|"
        r"cholesterol|ldl|hdl|triglycerides|psa|bnp|troponin|"
        r"iron|ferritin|vitd|vitamin\s*d|b12|folate|magnesium|phosphorus))"
        r"\s*[:\-=]?\s*"
        r"(?P<value>\d+(?:\.\d+)?)"
        r"\s*(?P<unit>(?:mg/(?:dL|dl)|g/(?:dL|dl)|mmol/L|mEq/L|U/L|"
        r"ng/(?:mL|ml)|pg/(?:mL|ml)|%|K/uL|M/uL|IU/L|mcg/dL|fL|"
        r"cells/uL|mIU/L|ng/dL|pmol/L)?)",
        re.IGNORECASE,
    )

    for match in lab_pattern.finditer(text):
        test_name = match.group("test").strip()
        value = match.group("value")
        unit = match.group("unit").strip() if match.group("unit") else ""

        fields.append(ExtractedField(
            field_name=test_name.lower(),
            value=float(value),
            category=FieldCategory.LAB_RESULT,
            confidence=0.6,
            source_document=source,
            source_span=match.group(0)[:100],
            extraction_method="regex",
            metadata={"unit": unit} if unit else {},
        ))

    return fields


def _extract_vitals(text: str, source: str) -> List[ExtractedField]:
    """Extract vital sign measurements."""
    fields = []
    vital_patterns = {
        "blood_pressure": r"(?:BP|blood\s+pressure)\s*[:\-=]?\s*(\d{2,3}\s*/\s*\d{2,3})\s*(?:mmHg)?",
        "heart_rate": r"(?:HR|heart\s+rate|pulse)\s*[:\-=]?\s*(\d{2,3})\s*(?:bpm|/min)?",
        "temperature": r"(?:temp|temperature)\s*[:\-=]?\s*(\d{2,3}(?:\.\d)?)\s*(?:°?[FC])?",
        "respiratory_rate": r"(?:RR|respiratory\s+rate|resp\s+rate)\s*[:\-=]?\s*(\d{1,2})\s*(?:/min)?",
        "spo2": r"(?:SpO2|O2\s*sat|oxygen\s+sat(?:uration)?)\s*[:\-=]?\s*(\d{2,3})\s*%?",
        "weight": r"(?:weight|wt)\s*[:\-=]?\s*(\d{2,4}(?:\.\d)?)\s*(?:kg|lbs?|pounds?)?",
        "height": r"(?:height|ht)\s*[:\-=]?\s*(\d{1,3}(?:\.\d)?)\s*(?:cm|in|inches|feet)?",
    }

    for vital_name, pattern in vital_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            fields.append(ExtractedField(
                field_name=vital_name,
                value=match.group(1).strip(),
                category=FieldCategory.VITAL_SIGN,
                confidence=0.65,
                source_document=source,
                source_span=match.group(0)[:100],
                extraction_method="regex",
            ))

    return fields


def _extract_diagnoses(text: str, source: str) -> List[ExtractedField]:
    """Extract diagnosis mentions and ICD codes."""
    fields = []

    # ICD-10 code pattern
    icd_pattern = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b")
    for match in icd_pattern.finditer(text):
        code = match.group(1)
        # Basic validation: ICD-10 starts with A-Z (not W, X, Y typically for external causes)
        if len(code) >= 3:
            fields.append(ExtractedField(
                field_name=f"icd10_{code}",
                value=code,
                category=FieldCategory.DIAGNOSIS,
                confidence=0.5,
                source_document=source,
                source_span=match.group(0)[:100],
                extraction_method="regex",
                metadata={"code_system": "ICD-10"},
            ))

    # Diagnosis patterns
    dx_patterns = [
        r"(?:diagnosis|diagnoses|dx|impression)\s*[:\-]\s*([^\n]{5,100})",
        r"(?:assessment)\s*[:\-]\s*([^\n]{5,100})",
    ]
    for pattern in dx_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            dx_text = match.group(1).strip()
            fields.append(ExtractedField(
                field_name="diagnosis",
                value=dx_text,
                category=FieldCategory.DIAGNOSIS,
                confidence=0.5,
                source_document=source,
                source_span=match.group(0)[:100],
                extraction_method="regex",
            ))

    return fields
