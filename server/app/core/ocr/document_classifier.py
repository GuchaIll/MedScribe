"""
Document type classifier for medical documents.

Uses LLM (Groq) to classify the extracted OCR text into
medical document categories such as lab report, prescription,
discharge summary, etc.

Falls back to keyword-based heuristic if the LLM is unavailable.
"""

from __future__ import annotations

import logging
import os
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Supported medical document types."""
    LAB_REPORT = "lab_report"
    RADIOLOGY_REPORT = "radiology_report"
    PRESCRIPTION = "prescription"
    MEDICAL_HISTORY = "medical_history"
    INSURANCE_FORM = "insurance_form"
    DISCHARGE_SUMMARY = "discharge_summary"
    REFERRAL = "referral"
    INTAKE_FORM = "intake_form"
    PROGRESS_NOTE = "progress_note"
    CONSULTATION = "consultation"
    UNKNOWN = "unknown"


@dataclass
class DocumentClassification:
    """Result of document type classification."""
    doc_type: DocumentType = DocumentType.UNKNOWN
    confidence: float = 0.0
    detected_sections: List[str] = field(default_factory=list)
    reasoning: str = ""


def classify_document(
    text: str,
    *,
    use_llm: bool = True,
    filename: Optional[str] = None,
) -> DocumentClassification:
    """
    Classify a medical document into a category.

    Parameters
    ----------
    text : str
        Extracted text from the document (first ~3000 chars used).
    use_llm : bool
        If True, use Groq LLM for classification.
    filename : str, optional
        Original filename (can provide hints).

    Returns
    -------
    DocumentClassification
    """
    if not text or not text.strip():
        return DocumentClassification(
            doc_type=DocumentType.UNKNOWN,
            confidence=0.0,
            reasoning="No text provided",
        )

    # Try filename-based hints first
    if filename:
        hint = _classify_by_filename(filename)
        if hint and hint.confidence >= 0.7:
            return hint

    if use_llm:
        result = _classify_via_llm(text)
        if result is not None:
            return result

    return _classify_heuristic(text)


def _classify_by_filename(filename: str) -> Optional[DocumentClassification]:
    """Quick classification from filename patterns."""
    name = filename.lower()
    mappings = {
        "lab": (DocumentType.LAB_REPORT, 0.7),
        "blood": (DocumentType.LAB_REPORT, 0.6),
        "cbc": (DocumentType.LAB_REPORT, 0.7),
        "cmp": (DocumentType.LAB_REPORT, 0.7),
        "xray": (DocumentType.RADIOLOGY_REPORT, 0.7),
        "x-ray": (DocumentType.RADIOLOGY_REPORT, 0.7),
        "ct_scan": (DocumentType.RADIOLOGY_REPORT, 0.7),
        "mri": (DocumentType.RADIOLOGY_REPORT, 0.7),
        "radiology": (DocumentType.RADIOLOGY_REPORT, 0.7),
        "prescription": (DocumentType.PRESCRIPTION, 0.8),
        "rx": (DocumentType.PRESCRIPTION, 0.6),
        "discharge": (DocumentType.DISCHARGE_SUMMARY, 0.8),
        "referral": (DocumentType.REFERRAL, 0.8),
        "insurance": (DocumentType.INSURANCE_FORM, 0.8),
        "intake": (DocumentType.INTAKE_FORM, 0.8),
        "progress": (DocumentType.PROGRESS_NOTE, 0.7),
        "consult": (DocumentType.CONSULTATION, 0.7),
        "history": (DocumentType.MEDICAL_HISTORY, 0.6),
    }
    for keyword, (doc_type, conf) in mappings.items():
        if keyword in name:
            return DocumentClassification(
                doc_type=doc_type,
                confidence=conf,
                reasoning=f"Filename contains '{keyword}'",
            )
    return None


def _classify_via_llm(text: str) -> Optional[DocumentClassification]:
    """Use Groq LLM to classify document type."""
    try:
        from groq import Groq
    except ImportError:
        logger.debug("groq not installed; falling back to heuristic")
        return None

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    # Use first 3000 chars for classification
    sample = text[:3000]
    valid_types = [t.value for t in DocumentType if t != DocumentType.UNKNOWN]

    prompt = f"""Classify the following medical document text into one of these categories:
{json.dumps(valid_types)}

Respond with ONLY a JSON object:
{{"doc_type": "<category>", "confidence": <0.0-1.0>, "detected_sections": ["section1", "section2"], "reasoning": "brief explanation"}}

Document text:
---
{sample}
---"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a medical document classifier. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        doc_type_str = result.get("doc_type", "unknown")

        # Validate doc_type
        try:
            doc_type = DocumentType(doc_type_str)
        except ValueError:
            doc_type = DocumentType.UNKNOWN

        return DocumentClassification(
            doc_type=doc_type,
            confidence=min(max(float(result.get("confidence", 0.5)), 0.0), 1.0),
            detected_sections=result.get("detected_sections", []),
            reasoning=result.get("reasoning", ""),
        )

    except Exception as e:
        logger.warning("LLM document classification failed: %s", e)
        return None


# ── Heuristic fallback ──────────────────────────────────────────────────────

# Keyword patterns that indicate document types
_DOCUMENT_PATTERNS: Dict[DocumentType, List[str]] = {
    DocumentType.LAB_REPORT: [
        r"\b(?:laboratory|lab\s+report|blood\s+test|cbc|cmp|metabolic\s+panel)\b",
        r"\b(?:hemoglobin|hematocrit|wbc|rbc|platelet|glucose|creatinine|bun)\b",
        r"\b(?:reference\s+range|normal\s+range|specimen|result|units?)\b",
    ],
    DocumentType.RADIOLOGY_REPORT: [
        r"\b(?:radiology|x-ray|ct\s+scan|mri|ultrasound|imaging)\b",
        r"\b(?:impression|findings|comparison|indication|technique)\b",
        r"\b(?:contrast|slice|axial|coronal|sagittal)\b",
    ],
    DocumentType.PRESCRIPTION: [
        r"\b(?:prescription|rx|prescribe|dispense|refill|pharmacy)\b",
        r"\b(?:sig|qty|tablets?|capsules?|mg|ml|bid|tid|qid|prn|daily)\b",
        r"\b(?:route|frequency|duration|substitution)\b",
    ],
    DocumentType.DISCHARGE_SUMMARY: [
        r"\b(?:discharge|discharged|hospital\s+course|admission)\b",
        r"\b(?:follow[-\s]?up|discharge\s+instructions|discharge\s+medications)\b",
        r"\b(?:admitting\s+diagnosis|discharge\s+diagnosis|length\s+of\s+stay)\b",
    ],
    DocumentType.MEDICAL_HISTORY: [
        r"\b(?:medical\s+history|past\s+medical|surgical\s+history|family\s+history)\b",
        r"\b(?:social\s+history|review\s+of\s+systems|immunizations?)\b",
        r"\b(?:chronic\s+conditions?|previous\s+surgeries)\b",
    ],
    DocumentType.REFERRAL: [
        r"\b(?:referral|refer(?:red|ring)\s+(?:to|by|physician))\b",
        r"\b(?:reason\s+for\s+referral|referring\s+provider|specialist)\b",
    ],
    DocumentType.INSURANCE_FORM: [
        r"\b(?:insurance|policy\s+number|group\s+number|subscriber|copay)\b",
        r"\b(?:claim|pre[-\s]?authorization|coverage|deductible|benefit)\b",
    ],
    DocumentType.INTAKE_FORM: [
        r"\b(?:intake|new\s+patient|registration|patient\s+information)\b",
        r"\b(?:emergency\s+contact|next\s+of\s+kin|consent|signature)\b",
    ],
    DocumentType.PROGRESS_NOTE: [
        r"\b(?:progress\s+note|daily\s+note|follow[-\s]?up\s+note)\b",
        r"\b(?:subjective|objective|assessment|plan|interval\s+history)\b",
    ],
    DocumentType.CONSULTATION: [
        r"\b(?:consultation|consult\s+note|specialist\s+report)\b",
        r"\b(?:reason\s+for\s+consultation|recommendations|impression)\b",
    ],
}

# Pre-compile patterns
_COMPILED_PATTERNS: Dict[DocumentType, List[re.Pattern]] = {
    doc_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for doc_type, patterns in _DOCUMENT_PATTERNS.items()
}


def _classify_heuristic(text: str) -> DocumentClassification:
    """Keyword-based document classification."""
    text_lower = text[:5000].lower()
    scores: Dict[DocumentType, float] = {}

    for doc_type, patterns in _COMPILED_PATTERNS.items():
        hits = 0
        for pattern in patterns:
            matches = pattern.findall(text_lower)
            hits += len(matches)
        if hits > 0:
            # Normalize: at least 1 hit from each pattern group = higher confidence
            patterns_matched = sum(
                1 for p in patterns if p.search(text_lower)
            )
            scores[doc_type] = min(
                0.3 + (patterns_matched / len(patterns)) * 0.5 + (hits * 0.02),
                0.85,
            )

    if not scores:
        return DocumentClassification(
            doc_type=DocumentType.UNKNOWN,
            confidence=0.1,
            reasoning="No keyword patterns matched",
        )

    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    # Detect sections from the text
    sections = _detect_sections(text)

    return DocumentClassification(
        doc_type=best_type,
        confidence=round(best_score, 2),
        detected_sections=sections,
        reasoning=f"Keyword match: scored {best_score:.2f} for {best_type.value}",
    )


def _detect_sections(text: str) -> List[str]:
    """Identify section headers in the document."""
    sections = []
    # Common section header patterns
    section_pattern = re.compile(
        r"^(?:[A-Z][A-Z\s/&]{2,}:?|(?:Chief Complaint|History of Present Illness|"
        r"Review of Systems|Physical Exam|Assessment|Plan|Medications|"
        r"Allergies|Lab Results|Vital Signs|Impression|Findings|"
        r"Discharge Instructions|Follow-Up|Subjective|Objective|"
        r"Hospital Course|Discharge Medications|Procedures?)[:\s]?)",
        re.MULTILINE,
    )
    for match in section_pattern.finditer(text[:5000]):
        header = match.group().strip().rstrip(":")
        if header and len(header) < 50 and header not in sections:
            sections.append(header)
    return sections[:20]
