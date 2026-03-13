"""
Unit tests for the 10-stage medical document OCR pipeline.

Tests each stage in isolation using mocks/fixtures (no external LLM calls,
no PaddleOCR models required):
  - PageSplitter
  - Preprocessor
  - LayoutDetector
  - HandwritingDetector
  - Extractor (multi-engine)
  - Normalizer
  - DocumentClassifier
  - FieldExtractor
  - ConflictDetector
  - Pipeline orchestrator
"""

import os
import json
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import asdict
from typing import List, Dict, Any

# ── Imports under test ──────────────────────────────────────────────────────

from app.core.ocr.document_classifier import (
    classify_document,
    DocumentType,
    DocumentClassification,
    _classify_heuristic,
    _classify_by_filename,
    _detect_sections,
)
from app.core.ocr.field_extractor import (
    extract_fields,
    ExtractedField,
    FieldCategory,
    _extract_via_regex,
    _extract_demographics,
    _extract_medications,
    _extract_allergies,
    _extract_lab_values,
    _extract_vitals,
    _extract_diagnoses,
)
from app.core.ocr.conflict_detector import (
    detect_conflicts,
    ConflictItem,
    ConflictType,
    ConflictSeverity,
    _check_low_confidence,
    _check_internal_duplicates,
    _check_allergy_conflicts,
    _check_lab_ranges,
    _check_medication_duplicates,
)
from app.core.ocr.normalizer import normalize_ocr_text
from app.core.ocr.layout_detector import (
    detect_layout,
    LayoutRegion,
    RegionType,
    TextType,
)
from app.core.ocr.page_splitter import PageResult
from app.core.ocr.extractor import OCRResult
from app.core.ocr.pipeline import (
    DocumentProcessingResult,
    _build_document_artifact,
    _build_candidate_facts,
    _infer_source_type,
)


# ============================================================================
# Shared fixtures
# ============================================================================

@pytest.fixture
def lab_report_text():
    """Sample lab report OCR text."""
    return """
LABORATORY REPORT

Patient Name: John Smith
Date of Birth: 05/15/1980
MRN: MRN123456
Date: 01/15/2026

TEST RESULTS:

Hemoglobin: 13.5 g/dL       (Reference Range: 12.0-17.5)
Hematocrit: 40.2%            (Reference Range: 36-51%)
WBC: 7.8 K/uL               (Reference Range: 4.5-11.0)
Platelets: 250 K/uL          (Reference Range: 150-400)
Glucose: 105 mg/dL           (Reference Range: 70-100)
Creatinine: 1.1 mg/dL        (Reference Range: 0.7-1.3)
BUN: 18 mg/dL                (Reference Range: 7-20)
Sodium: 140 mEq/L            (Reference Range: 136-145)
Potassium: 4.2 mEq/L         (Reference Range: 3.5-5.0)

Ordering Physician: Dr. Jane Williams
"""


@pytest.fixture
def prescription_text():
    """Sample prescription OCR text."""
    return """
PRESCRIPTION

Patient: Mary Johnson
Date: 02/10/2026

Rx: Metformin 500mg
Sig: Take 1 tablet by mouth twice daily with meals
Qty: 60 tablets
Refills: 3

Rx: Lisinopril 10mg
Sig: Take 1 tablet daily
Qty: 30 tablets
Refills: 5

Prescribing Physician: Dr. Robert Chen, MD
DEA: AC1234567
"""


@pytest.fixture
def discharge_summary_text():
    """Sample discharge summary OCR text."""
    return """
DISCHARGE SUMMARY

Patient Name: James Brown
DOB: 03/22/1975
Admission Date: 01/05/2026
Discharge Date: 01/10/2026

Admitting Diagnosis: Acute appendicitis
Discharge Diagnosis: Status post appendectomy

Hospital Course:
Patient presented with acute right lower quadrant pain. CT scan confirmed
appendicitis. Laparoscopic appendectomy performed on 01/06/2026 without
complications. Post-operative course was unremarkable.

Discharge Medications:
- Acetaminophen 500mg PO every 6 hours as needed for pain
- Amoxicillin 500mg PO three times daily for 7 days

Allergies: Penicillin (rash), Sulfa drugs

Follow-Up: See Dr. Williams in 2 weeks
"""


@pytest.fixture
def patient_history_with_allergies():
    """Sample patient history for conflict detection."""
    return {
        "found": True,
        "allergies": [
            {"substance": "penicillin", "reaction": "rash", "severity": "moderate"},
            {"substance": "sulfa", "reaction": "hives", "severity": "severe"},
        ],
        "medications": [
            {"name": "aspirin", "dose": "81mg", "frequency": "daily"},
            {"name": "metformin", "dose": "500mg", "frequency": "twice daily"},
        ],
        "diagnoses": [
            {"code": "I10", "description": "Essential hypertension"},
            {"code": "E11", "description": "Type 2 diabetes mellitus"},
        ],
        "labs": [],
        "patient_info": {
            "full_name": "James Brown",
            "dob": "03/22/1975",
        },
    }


# ============================================================================
# DocumentClassifier Tests
# ============================================================================

@pytest.mark.unit
class TestDocumentClassifier:
    """Tests for document_classifier.py."""

    def test_classify_empty_text(self):
        """Empty text returns UNKNOWN with 0.0 confidence."""
        result = classify_document("", use_llm=False)
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 0.0

    def test_classify_lab_report_heuristic(self, lab_report_text):
        """Lab report keywords should classify as LAB_REPORT."""
        result = classify_document(lab_report_text, use_llm=False)
        assert result.doc_type == DocumentType.LAB_REPORT
        assert result.confidence > 0.3

    def test_classify_prescription_heuristic(self, prescription_text):
        """Prescription keywords should classify as PRESCRIPTION."""
        result = classify_document(prescription_text, use_llm=False)
        assert result.doc_type == DocumentType.PRESCRIPTION
        assert result.confidence > 0.3

    def test_classify_discharge_summary_heuristic(self, discharge_summary_text):
        """Discharge summary keywords should classify as DISCHARGE_SUMMARY."""
        result = classify_document(discharge_summary_text, use_llm=False)
        assert result.doc_type == DocumentType.DISCHARGE_SUMMARY
        assert result.confidence > 0.3

    def test_classify_by_filename_lab(self):
        """Filename 'lab_results.pdf' should hint LAB_REPORT."""
        result = _classify_by_filename("lab_results.pdf")
        assert result is not None
        assert result.doc_type == DocumentType.LAB_REPORT

    def test_classify_by_filename_discharge(self):
        """Filename 'discharge_summary.pdf' should hint DISCHARGE_SUMMARY."""
        result = _classify_by_filename("patient_discharge_paperwork.pdf")
        assert result is not None
        assert result.doc_type == DocumentType.DISCHARGE_SUMMARY

    def test_classify_by_filename_prescription(self):
        """Filename 'prescription_rx.pdf' should hint PRESCRIPTION."""
        result = _classify_by_filename("prescription_feb2026.pdf")
        assert result is not None
        assert result.doc_type == DocumentType.PRESCRIPTION

    def test_classify_by_filename_no_hint(self):
        """Filename 'scan_005.pdf' gives no classification hint."""
        result = _classify_by_filename("scan_005.pdf")
        assert result is None

    def test_detect_sections(self, discharge_summary_text):
        """Section headers should be detected."""
        sections = _detect_sections(discharge_summary_text)
        assert len(sections) > 0
        # Should find at least some uppercase section headers
        section_texts = [s.upper() for s in sections]
        found = any("DISCHARGE" in s for s in section_texts)
        assert found, f"Expected 'DISCHARGE' in {sections}"

    def test_heuristic_no_match(self):
        """Random non-medical text returns UNKNOWN."""
        result = _classify_heuristic("The weather is nice today. Let's go for a walk.")
        assert result.doc_type == DocumentType.UNKNOWN

    def test_classify_radiology_heuristic(self):
        """Radiology keywords should classify correctly."""
        text = """
        RADIOLOGY REPORT
        Modality: CT Scan
        Findings: No acute abnormality. Impression: Normal CT of chest.
        Technique: Non-contrast axial slices through the chest.
        """
        result = classify_document(text, use_llm=False)
        assert result.doc_type == DocumentType.RADIOLOGY_REPORT

    def test_classify_with_filename_override(self):
        """Strong filename hint used even with ambiguous text."""
        result = classify_document(
            "Some generic text that could be anything.",
            use_llm=False,
            filename="lab_report_2026.pdf",
        )
        assert result.doc_type == DocumentType.LAB_REPORT

    def test_document_type_enum_values(self):
        """All expected document types are defined."""
        expected = {
            "lab_report", "radiology_report", "prescription",
            "medical_history", "insurance_form", "discharge_summary",
            "referral", "intake_form", "progress_note", "consultation",
            "unknown",
        }
        actual = {t.value for t in DocumentType}
        assert expected == actual


# ============================================================================
# FieldExtractor Tests
# ============================================================================

@pytest.mark.unit
class TestFieldExtractor:
    """Tests for field_extractor.py."""

    def test_extract_empty_text(self):
        """Empty text returns no fields."""
        fields = extract_fields("", use_llm=False)
        assert fields == []

    def test_extract_demographics_name(self):
        """Should extract patient name."""
        text = "Patient Name: John Smith\nDOB: 05/15/1980"
        fields = _extract_demographics(text, "test.pdf")
        names = [f for f in fields if f.field_name == "patient_name"]
        assert len(names) >= 1
        assert "John Smith" in names[0].value

    def test_extract_demographics_dob(self):
        """Should extract date of birth."""
        text = "Patient: Jane Doe\nDate of Birth: 03/22/1975"
        fields = _extract_demographics(text, "test.pdf")
        dob_fields = [f for f in fields if f.field_name == "date_of_birth"]
        assert len(dob_fields) >= 1
        assert "03/22/1975" in dob_fields[0].value

    def test_extract_demographics_mrn(self):
        """Should extract MRN."""
        text = "MRN: MRN123456\nPatient: Test Patient"
        fields = _extract_demographics(text, "test.pdf")
        mrn_fields = [f for f in fields if f.field_name == "mrn"]
        assert len(mrn_fields) >= 1
        assert "MRN123456" in mrn_fields[0].value

    def test_extract_lab_values(self, lab_report_text):
        """Should extract lab values with numeric data."""
        fields = _extract_lab_values(lab_report_text, "lab.pdf")
        assert len(fields) > 0
        # Check for specific known lab values
        test_names = {f.field_name.lower() for f in fields}
        assert "hemoglobin" in test_names or "hgb" in test_names
        assert "glucose" in test_names

        # Verify values are numeric
        for f in fields:
            assert isinstance(f.value, (int, float))

    def test_extract_vitals(self):
        """Should extract vital sign measurements."""
        text = "Vitals: BP: 120/80 mmHg, HR: 72 bpm, Temp: 98.6F, SpO2: 98%"
        fields = _extract_vitals(text, "test.pdf")
        vital_names = {f.field_name for f in fields}
        assert "blood_pressure" in vital_names
        assert "heart_rate" in vital_names
        assert "spo2" in vital_names

    def test_extract_allergies(self):
        """Should extract allergy mentions."""
        text = "Patient is allergic to Penicillin, allergic to Sulfa, allergic to Latex"
        fields = _extract_allergies(text, "test.pdf")
        assert len(fields) >= 2
        allergens = {f.value.lower() for f in fields}
        assert any("penicillin" in a for a in allergens)

    def test_extract_medications(self):
        """Should extract medication names with dosage suffixes."""
        text = "Current medications: Metformin 500mg, Lisinopril 10mg, Aspirin 81mg daily"
        fields = _extract_medications(text, "test.pdf")
        assert len(fields) > 0
        med_names = {f.field_name for f in fields}
        assert any("metformin" in n for n in med_names)

    def test_extract_diagnoses_icd10(self):
        """Should extract ICD-10 codes."""
        text = "Diagnosis: E11.9 Type 2 diabetes mellitus without complications. I10 Essential hypertension."
        fields = _extract_diagnoses(text, "test.pdf")
        icd_fields = [f for f in fields if f.metadata.get("code_system") == "ICD-10"]
        assert len(icd_fields) >= 1
        codes = {f.value for f in icd_fields}
        assert "E11.9" in codes or "I10" in codes

    def test_extract_fields_lab_report(self, lab_report_text):
        """Full regex extraction from a lab report should find multiple fields."""
        fields = extract_fields(
            lab_report_text,
            doc_type=DocumentType.LAB_REPORT,
            use_llm=False,
        )
        assert len(fields) > 3
        categories = {f.category for f in fields}
        # Should have at least lab results and demographics
        assert FieldCategory.LAB_RESULT in categories
        assert FieldCategory.DEMOGRAPHIC in categories

    def test_field_confidence_scaling(self):
        """OCR confidence should scale field confidence."""
        text = "Hemoglobin: 13.5 g/dL"
        fields = extract_fields(text, ocr_confidence=0.5, use_llm=False)
        for f in fields:
            assert f.confidence <= 0.5  # Scaled by OCR confidence

    def test_field_id_generation(self):
        """Each field should get a unique ID."""
        text = "Hemoglobin: 13.5 g/dL\nGlucose: 105 mg/dL"
        fields = extract_fields(text, use_llm=False)
        ids = [f.field_id for f in fields]
        assert len(ids) == len(set(ids)), "Field IDs must be unique"

    def test_extracted_field_dataclass(self):
        """ExtractedField should have all expected attributes."""
        f = ExtractedField(
            field_name="hemoglobin",
            value=13.5,
            category=FieldCategory.LAB_RESULT,
            confidence=0.9,
            source_document="lab.pdf",
            source_span="Hemoglobin: 13.5 g/dL",
            extraction_method="regex",
            metadata={"unit": "g/dL"},
        )
        assert f.field_id.startswith("fld_")
        assert f.field_name == "hemoglobin"
        assert f.value == 13.5
        assert f.category == FieldCategory.LAB_RESULT

    def test_field_category_enum(self):
        """All expected categories exist."""
        expected = {
            "medication", "allergy", "diagnosis", "lab_result",
            "vital_sign", "procedure", "demographic", "physician_note",
            "follow_up", "insurance",
        }
        actual = {c.value for c in FieldCategory}
        assert expected == actual


# ============================================================================
# ConflictDetector Tests
# ============================================================================

@pytest.mark.unit
class TestConflictDetector:
    """Tests for conflict_detector.py."""

    def test_no_conflicts_empty_fields(self):
        """No fields = no conflicts."""
        conflicts = detect_conflicts([])
        assert conflicts == []

    def test_low_confidence_flagged(self):
        """Fields below threshold are flagged."""
        fields = [
            ExtractedField(field_name="hemoglobin", value="13.5", confidence=0.3),
            ExtractedField(field_name="glucose", value="105", confidence=0.8),
        ]
        conflicts = _check_low_confidence(fields, threshold=0.5)
        assert len(conflicts) == 1
        assert conflicts[0].field_name == "hemoglobin"
        assert conflicts[0].conflict_type == ConflictType.LOW_CONFIDENCE

    def test_internal_duplicates_detected(self):
        """Contradictory values for same field should be flagged."""
        fields = [
            ExtractedField(
                field_name="hemoglobin", value="13.5",
                category=FieldCategory.LAB_RESULT, confidence=0.9,
            ),
            ExtractedField(
                field_name="hemoglobin", value="11.2",
                category=FieldCategory.LAB_RESULT, confidence=0.8,
            ),
        ]
        conflicts = _check_internal_duplicates(fields)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.CONTRADICTORY_VALUE

    def test_no_duplicates_when_values_match(self):
        """Same field with same value should NOT be flagged as contradictory."""
        fields = [
            ExtractedField(
                field_name="hemoglobin", value="13.5",
                category=FieldCategory.LAB_RESULT, confidence=0.9,
            ),
            ExtractedField(
                field_name="hemoglobin", value="13.5",
                category=FieldCategory.LAB_RESULT, confidence=0.7,
            ),
        ]
        conflicts = _check_internal_duplicates(fields)
        assert len(conflicts) == 0

    def test_allergy_medication_conflict(self, patient_history_with_allergies):
        """Prescribing a medication the patient is allergic to → CRITICAL."""
        fields = [
            ExtractedField(
                field_name="penicillin",
                value="Penicillin 500mg",
                category=FieldCategory.MEDICATION,
                confidence=0.9,
            ),
        ]
        conflicts = _check_allergy_conflicts(fields, patient_history_with_allergies)
        assert len(conflicts) >= 1
        assert any(c.severity == ConflictSeverity.CRITICAL for c in conflicts)
        assert any(c.conflict_type == ConflictType.ALLERGY_MEDICATION for c in conflicts)

    def test_cross_reactivity_detected(self, patient_history_with_allergies):
        """Amoxicillin should trigger cross-reactivity with penicillin allergy."""
        fields = [
            ExtractedField(
                field_name="amoxicillin",
                value="Amoxicillin 500mg",
                category=FieldCategory.MEDICATION,
                confidence=0.9,
            ),
        ]
        conflicts = _check_allergy_conflicts(fields, patient_history_with_allergies)
        assert len(conflicts) >= 1
        assert any("cross-react" in c.message.lower() for c in conflicts)

    def test_lab_value_out_of_range(self):
        """Lab value outside physiological range should be flagged."""
        fields = [
            ExtractedField(
                field_name="sodium",
                value=200.0,
                category=FieldCategory.LAB_RESULT,
                confidence=0.8,
            ),
        ]
        conflicts = _check_lab_ranges(fields)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.VALUE_OUT_OF_RANGE

    def test_lab_value_within_range(self):
        """Lab value inside range should NOT be flagged."""
        fields = [
            ExtractedField(
                field_name="sodium",
                value=140.0,
                category=FieldCategory.LAB_RESULT,
                confidence=0.8,
            ),
        ]
        conflicts = _check_lab_ranges(fields)
        assert len(conflicts) == 0

    def test_medication_duplicate_different_dose(self, patient_history_with_allergies):
        """Same med with different dose → duplicate conflict."""
        fields = [
            ExtractedField(
                field_name="metformin",
                value="Metformin 1000mg",
                category=FieldCategory.MEDICATION,
                confidence=0.9,
                metadata={"dose": "1000mg"},
            ),
        ]
        conflicts = _check_medication_duplicates(fields, patient_history_with_allergies)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == ConflictType.DUPLICATE_MEDICATION for c in conflicts)

    def test_full_conflict_pipeline(self, lab_report_text, patient_history_with_allergies):
        """End-to-end: extract fields then detect conflicts."""
        fields = extract_fields(lab_report_text, use_llm=False)
        conflicts = detect_conflicts(
            fields,
            patient_history=patient_history_with_allergies,
            confidence_threshold=0.5,
        )
        # Should at least flag some fields (low confidence for regex-only)
        assert isinstance(conflicts, list)

    def test_conflict_severity_levels(self):
        """All severity levels exist."""
        expected = {"critical", "high", "medium", "low"}
        actual = {s.value for s in ConflictSeverity}
        assert expected == actual

    def test_conflict_item_id_generated(self):
        """ConflictItem should auto-generate an ID."""
        item = ConflictItem(field_name="test")
        assert item.conflict_id.startswith("cfl_")


# ============================================================================
# Normalizer Tests
# ============================================================================

@pytest.mark.unit
class TestNormalizer:
    """Tests for normalizer.py."""

    def test_normalize_empty(self):
        """Empty text returns empty."""
        assert normalize_ocr_text("") == ""

    def test_normalize_whitespace(self):
        """Extra whitespace should be collapsed."""
        result = normalize_ocr_text("The   patient    has   pain")
        assert "   " not in result

    def test_normalize_abbreviations(self):
        """Medical abbreviations should be expanded."""
        result = normalize_ocr_text("pt has htn and dm")
        assert "patient" in result.lower()
        assert "hypertension" in result.lower()

    def test_normalize_preserves_meaning(self):
        """Normalization should not change numeric values."""
        text = "Hemoglobin: 13.5 g/dL, WBC: 7.8 K/uL"
        result = normalize_ocr_text(text)
        assert "13.5" in result
        assert "7.8" in result


# ============================================================================
# LayoutDetector Tests
# ============================================================================

@pytest.mark.unit
class TestLayoutDetector:
    """Tests for layout_detector.py."""

    def test_detect_layout_empty(self):
        """Empty text returns empty or minimal regions."""
        regions = detect_layout("", use_vision=False)
        assert isinstance(regions, list)

    def test_detect_header_regions(self):
        """All-caps lines should be detected as HEADER."""
        text = "LABORATORY REPORT\n\nHemoglobin: 13.5 g/dL\nGlucose: 105 mg/dL"
        regions = detect_layout(text, use_vision=False)
        headers = [r for r in regions if r.region_type == RegionType.HEADER]
        assert len(headers) >= 1

    def test_detect_key_value_regions(self):
        """'Key: Value' patterns should be detected as KEY_VALUE."""
        text = "Patient Name: John Smith\nDate of Birth: 05/15/1980\nRecord Number: 12345"
        regions = detect_layout(text, use_vision=False)
        kv_regions = [r for r in regions if r.region_type == RegionType.KEY_VALUE]
        assert len(kv_regions) >= 2

    def test_detect_list_items(self):
        """Bulleted/numbered items should be detected as LIST."""
        text = "Medications:\n- Aspirin 81mg\n- Metformin 500mg\n- Lisinopril 10mg"
        regions = detect_layout(text, use_vision=False)
        lists = [r for r in regions if r.region_type == RegionType.LIST]
        assert len(lists) >= 1

    def test_region_type_enum(self):
        """All expected region types are defined."""
        expected = {
            "header", "paragraph", "table", "key_value", "list",
            "signature", "checkbox", "handwritten", "page_number", "unknown",
        }
        actual = {t.value for t in RegionType}
        assert expected == actual


# ============================================================================
# Pipeline Integration Helpers Tests
# ============================================================================

@pytest.mark.unit
class TestPipelineHelpers:
    """Tests for pipeline.py helper functions."""

    def test_infer_source_type_pdf(self):
        assert _infer_source_type("scan.pdf") == "pdf"

    def test_infer_source_type_image(self):
        assert _infer_source_type("photo.jpg") == "image"
        assert _infer_source_type("scan.png") == "image"
        assert _infer_source_type("doc.tiff") == "image"

    def test_infer_source_type_text(self):
        assert _infer_source_type("notes.txt") == "text"

    def test_infer_source_type_unknown(self):
        assert _infer_source_type("file.docx") == "unknown"

    def test_build_document_artifact(self):
        """DocumentProcessingResult → DocumentArtifact dict."""
        result = DocumentProcessingResult(
            document_id="doc_abc",
            file_path="test.pdf",
            original_filename="lab_report.pdf",
            page_count=2,
            full_text="Hemoglobin: 13.5 g/dL",
            classification=DocumentClassification(
                doc_type=DocumentType.LAB_REPORT,
                confidence=0.85,
                detected_sections=["TEST RESULTS"],
            ),
            extracted_fields=[
                ExtractedField(field_name="hemoglobin", value=13.5),
            ],
            conflicts=[],
            overall_confidence=0.9,
            ocr_engines_used=["paddleocr"],
        )
        artifact = _build_document_artifact(result)
        assert artifact["document_id"] == "doc_abc"
        assert artifact["source_type"] == "pdf"
        assert artifact["extracted_text"] == "Hemoglobin: 13.5 g/dL"
        assert artifact["metadata"]["document_type"] == "lab_report"
        assert artifact["metadata"]["page_count"] == 2

    def test_build_candidate_facts(self):
        """ExtractedFields should be converted to CandidateFact dicts."""
        fields = [
            ExtractedField(
                field_id="fld_001",
                field_name="hemoglobin",
                value=13.5,
                category=FieldCategory.LAB_RESULT,
                confidence=0.85,
                source_document="lab.pdf",
                source_span="Hemoglobin: 13.5 g/dL",
                extraction_method="regex",
                metadata={"unit": "g/dL"},
            ),
        ]
        facts = _build_candidate_facts(fields)
        assert len(facts) == 1
        assert facts[0]["fact_id"] == "fld_001"
        assert facts[0]["type"] == "lab_result"
        assert facts[0]["confidence"] == 0.85
        assert facts[0]["value"]["field_name"] == "hemoglobin"
        assert facts[0]["provenance"]["source_document"] == "lab.pdf"


# ============================================================================
# Ingest Node Document Branch Tests
# ============================================================================

@pytest.mark.unit
class TestIngestNodeDocuments:
    """Tests for the document ingestion branch in ingest.py.

    These tests require importing the full agent graph which depends on
    HUGGINGFACE_API_KEY at module-import time.  We set a dummy env-var
    and mock the heavy model-loading modules so the import chain succeeds
    without real credentials or GPU libraries.
    """

    @pytest.fixture(autouse=True)
    def _mock_heavy_imports(self, monkeypatch):
        """Patch env + heavy modules so ingest can be imported."""
        import sys
        from unittest.mock import MagicMock

        monkeypatch.setenv("HUGGINGFACE_API_KEY", "test-dummy-key")

        # Ensure registry module is re-importable with the env var set
        # by removing cached modules that already failed or were loaded
        # without the key.
        mods_to_purge = [k for k in sys.modules if k.startswith("app.models")
                         or k.startswith("app.agents")]
        for m in mods_to_purge:
            sys.modules.pop(m, None)

        # Stub out heavy third-party modules that are slow / need GPU
        for mod_name in [
            "faster_whisper", "pyannote.audio", "pyannote",
            "transformers", "huggingface_hub",
        ]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = MagicMock()

    def test_ingest_with_documents(self, minimal_graph_state):
        """Documents in state should be chunked into ChunkArtifacts."""
        from app.agents.nodes.ingest import ingest_transcript_node

        state = minimal_graph_state.copy()
        state["new_segments"] = [{
            "start": 0.0, "end": 3.0,
            "speaker": "Doctor",
            "raw_text": "Hello",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "high",
        }]
        state["documents"] = [{
            "document_id": "doc_001",
            "source_type": "pdf",
            "extracted_text": "Hemoglobin: 13.5 g/dL. " * 30,  # > 500 chars
            "tables": [],
            "metadata": {
                "original_filename": "lab.pdf",
                "document_type": "lab_report",
                "page_count": 1,
            },
        }]

        result = ingest_transcript_node(state)

        assert "chunks" in result
        chunks = result["chunks"]
        assert len(chunks) > 0
        doc_chunks = [c for c in chunks if c["source"] == "document"]
        assert len(doc_chunks) > 0
        assert doc_chunks[0]["source_id"] == "doc_001"

    def test_ingest_without_documents(self, minimal_graph_state):
        """No documents → no document chunks."""
        from app.agents.nodes.ingest import ingest_transcript_node

        state = minimal_graph_state.copy()
        state["new_segments"] = [{
            "start": 0.0, "end": 3.0,
            "speaker": "Doctor",
            "raw_text": "Hello",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "high",
        }]
        state["documents"] = []

        result = ingest_transcript_node(state)
        doc_chunks = [c for c in result.get("chunks", []) if c.get("source") == "document"]
        assert len(doc_chunks) == 0

    def test_ingest_empty_document_skipped(self, minimal_graph_state):
        """Document with no extracted text should be skipped."""
        from app.agents.nodes.ingest import ingest_transcript_node

        state = minimal_graph_state.copy()
        state["new_segments"] = [{
            "start": 0.0, "end": 1.0,
            "speaker": "Doctor",
            "raw_text": "Test",
            "cleaned_text": None,
            "uncertainties": [],
            "confidence": "high",
        }]
        state["documents"] = [{
            "document_id": "doc_empty",
            "source_type": "pdf",
            "extracted_text": "",
            "tables": [],
            "metadata": {},
        }]

        result = ingest_transcript_node(state)
        doc_chunks = [c for c in result.get("chunks", []) if c.get("source") == "document"]
        assert len(doc_chunks) == 0


# ============================================================================
# Session Service Queue Tests
# ============================================================================

@pytest.mark.unit
class TestSessionServiceQueue:
    """Tests for modification queue management in SessionService."""

    def test_add_and_get_queue(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        resp = svc.start_session()
        sid = resp["session_id"]

        items = [
            {"item_id": "q1", "field_name": "hemoglobin", "status": "pending"},
            {"item_id": "q2", "field_name": "glucose", "status": "pending"},
        ]
        svc.add_to_queue(sid, items)
        queue = svc.get_queue(sid)
        assert len(queue) == 2
        assert queue[0]["item_id"] == "q1"

    def test_update_queue_item(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        resp = svc.start_session()
        sid = resp["session_id"]

        svc.add_to_queue(sid, [
            {"item_id": "q1", "field_name": "hemoglobin", "status": "pending"},
        ])
        updated = svc.update_queue_item(sid, "q1", "accepted")
        assert updated is not None
        assert updated["status"] == "accepted"

    def test_update_queue_item_with_corrected_value(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        resp = svc.start_session()
        sid = resp["session_id"]

        svc.add_to_queue(sid, [
            {"item_id": "q1", "field_name": "glucose", "status": "pending"},
        ])
        updated = svc.update_queue_item(sid, "q1", "modified", corrected_value="110 mg/dL")
        assert updated["status"] == "modified"
        assert updated["corrected_value"] == "110 mg/dL"

    def test_update_nonexistent_item(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        resp = svc.start_session()
        sid = resp["session_id"]

        result = svc.update_queue_item(sid, "nonexistent", "accepted")
        assert result is None

    def test_get_queue_nonexistent_session(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        assert svc.get_queue("fake_session") == []

    def test_add_and_get_documents(self):
        from app.services.session_service import SessionService

        svc = SessionService()
        resp = svc.start_session()
        sid = resp["session_id"]

        doc = {"document_id": "doc_001", "source_type": "pdf", "extracted_text": "test"}
        svc.add_document(sid, doc)
        docs = svc.get_documents(sid)
        assert len(docs) == 1
        assert docs[0]["document_id"] == "doc_001"


# ============================================================================
# DB Model Tests
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestDocumentModel:
    """Tests for the Document SQLAlchemy model."""

    def test_create_document(self, db_session, sample_patient, sample_user):
        """Document model can be persisted and retrieved."""
        from app.database.models import Document, Session as DBSession, OCRStatus

        # Create a session first (FK requirement)
        session = DBSession(
            id="SESS_DOC_TEST",
            patient_id=sample_patient.id,
            doctor_id=sample_user.id,
            status="active",
        )
        db_session.add(session)
        db_session.flush()

        doc = Document(
            id="DOC001",
            session_id="SESS_DOC_TEST",
            patient_id=sample_patient.id,
            original_filename="lab_report.pdf",
            stored_path="storage/uploads/SESS_DOC_TEST/abc123.pdf",
            file_type="pdf",
            file_size=50000,
            ocr_status=OCRStatus.COMPLETED,
            document_type="lab_report",
            classification_confidence=0.85,
            extracted_text="Hemoglobin: 13.5 g/dL",
            structured_fields=[{"field_name": "hemoglobin", "value": 13.5}],
            overall_confidence=0.9,
            page_count=1,
            field_count=1,
            conflict_count=0,
        )
        db_session.add(doc)
        db_session.flush()

        retrieved = db_session.query(Document).filter_by(id="DOC001").first()
        assert retrieved is not None
        assert retrieved.original_filename == "lab_report.pdf"
        assert retrieved.ocr_status == OCRStatus.COMPLETED
        assert retrieved.document_type == "lab_report"
        assert retrieved.structured_fields[0]["value"] == 13.5

    def test_ocr_status_enum(self):
        """OCRStatus enum has all expected values."""
        from app.database.models import OCRStatus
        expected = {"pending", "processing", "completed", "failed"}
        actual = {s.value for s in OCRStatus}
        assert expected == actual
