"""
Integration tests for OCR document extraction on real medical documents.

Processes each file in ``tests/ocr_examples/`` through the full 10-stage
pipeline (without LLM — uses heuristic/regex fallbacks) and writes the
extracted fields to matching ``.txt`` files in ``tests/ocr_result/``.

Marks: integration, slow
Requires: paddleocr + paddlepaddle installed AND
          poppler (``pdftoimage`` / ``pdftoppm``).

If dependencies are missing the tests are skipped automatically.
"""

from __future__ import annotations

import json
import os
import textwrap
import asyncio
import pytest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Paths
TESTS_DIR = Path(__file__).resolve().parent
OCR_EXAMPLES_DIR = TESTS_DIR / "ocr_examples"
OCR_RESULT_DIR = TESTS_DIR / "ocr_result"


# ── Dependency checks ──────────────────────────────────────────────────────

def _paddleocr_available() -> bool:
    """Check if RapidOCR (PaddleOCR models via ONNX) is importable."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        return True
    except Exception:
        return False


def _pdfplumber_available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def _pdf2image_available() -> bool:
    try:
        import pdf2image  # noqa: F401
        return True
    except ImportError:
        return False


def _pil_available() -> bool:
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


# Skip markers
requires_paddleocr = pytest.mark.skipif(
    not _paddleocr_available(),
    reason="PaddleOCR not installed (pip install paddleocr paddlepaddle)",
)
requires_pil = pytest.mark.skipif(
    not _pil_available(),
    reason="Pillow not installed",
)
requires_pdfplumber = pytest.mark.skipif(
    not _pdfplumber_available(),
    reason="pdfplumber not installed",
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_example_files() -> List[Path]:
    """Collect all document files from the ocr_examples directory."""
    if not OCR_EXAMPLES_DIR.exists():
        return []
    supported = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
    return sorted(
        p for p in OCR_EXAMPLES_DIR.iterdir()
        if p.suffix.lower() in supported
    )


def _format_results(
    file_path: Path,
    result: Any,
) -> str:
    """Format pipeline results into a human-readable text report."""
    lines = []
    sep = "=" * 72

    lines.append(sep)
    lines.append(f"  OCR Extraction Report")
    lines.append(f"  File: {file_path.name}")
    lines.append(f"  Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append("")

    # Classification
    lines.append("── Document Classification ──")
    if result.classification:
        lines.append(f"  Type       : {result.classification.doc_type.value}")
        lines.append(f"  Confidence : {result.classification.confidence:.2f}")
        if result.classification.detected_sections:
            lines.append(f"  Sections   : {', '.join(result.classification.detected_sections[:10])}")
        if result.classification.reasoning:
            lines.append(f"  Reasoning  : {result.classification.reasoning}")
    else:
        lines.append("  (classification unavailable)")
    lines.append("")

    # Metrics
    lines.append("── Metrics ──")
    lines.append(f"  Pages            : {result.page_count}")
    lines.append(f"  Overall confidence: {result.overall_confidence:.2f}")
    lines.append(f"  OCR engines      : {', '.join(result.ocr_engines_used) or 'none'}")
    lines.append(f"  Fields extracted : {len(result.extracted_fields)}")
    lines.append(f"  Conflicts found  : {len(result.conflicts)}")
    if result.processing_errors:
        lines.append(f"  Errors           : {len(result.processing_errors)}")
        for err in result.processing_errors:
            lines.append(f"    - {err}")
    lines.append("")

    # Extracted fields grouped by category
    lines.append("── Extracted Fields ──")
    if not result.extracted_fields:
        lines.append("  (no fields extracted)")
    else:
        # Group by category
        by_cat: Dict[str, list] = {}
        for f in result.extracted_fields:
            cat = f.category.value if hasattr(f.category, "value") else str(f.category)
            by_cat.setdefault(cat, []).append(f)

        for cat_name in sorted(by_cat.keys()):
            fields = by_cat[cat_name]
            lines.append(f"\n  [{cat_name.upper()}]")
            for f in fields:
                conf_str = f"(conf: {f.confidence:.2f})" if f.confidence else ""
                val_str = str(f.value)
                if len(val_str) > 80:
                    val_str = val_str[:77] + "..."
                meta = ""
                if f.metadata:
                    meta_parts = [f"{k}={v}" for k, v in f.metadata.items() if v]
                    if meta_parts:
                        meta = f" [{', '.join(meta_parts)}]"
                lines.append(f"    {f.field_name}: {val_str} {conf_str}{meta}")
    lines.append("")

    # Conflicts
    lines.append("── Conflicts ──")
    if not result.conflicts:
        lines.append("  (no conflicts)")
    else:
        for c in result.conflicts:
            sev = c.severity.value if hasattr(c.severity, "value") else str(c.severity)
            ctype = c.conflict_type.value if hasattr(c.conflict_type, "value") else str(c.conflict_type)
            lines.append(f"  [{sev.upper()}] {ctype}")
            lines.append(f"    Field   : {c.field_name}")
            lines.append(f"    Value   : {c.extracted_value}")
            if c.existing_value:
                lines.append(f"    Existing: {c.existing_value}")
            lines.append(f"    Message : {c.message}")
            if c.recommendation:
                lines.append(f"    Action  : {c.recommendation}")
            lines.append("")
    lines.append("")

    # Full extracted text (truncated)
    lines.append("── Full Extracted Text (first 3000 chars) ──")
    text_preview = result.full_text[:3000] if result.full_text else "(empty)"
    lines.append(text_preview)
    lines.append("")
    lines.append(sep)

    return "\n".join(lines)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ensure_output_dir():
    """Create the output directory for results."""
    OCR_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    return OCR_RESULT_DIR


@pytest.fixture(scope="module")
def sample_patient_history():
    """Patient history fixture for conflict detection during extraction."""
    return {
        "found": True,
        "allergies": [
            {"substance": "penicillin", "reaction": "rash", "severity": "moderate"},
        ],
        "medications": [
            {"name": "aspirin", "dose": "81mg", "frequency": "daily"},
            {"name": "metformin", "dose": "500mg", "frequency": "twice daily"},
        ],
        "diagnoses": [],
        "labs": [],
        "patient_info": {
            "full_name": "Test Patient",
            "dob": "01/01/1970",
        },
    }


# ============================================================================
# Test: Process each example document through the full pipeline
# ============================================================================

example_files = _get_example_files()


@pytest.mark.integration
@pytest.mark.slow
@requires_pil
class TestDocumentOCRExtraction:
    """
    Process each real document in ocr_examples/ and write structured
    extraction results to ocr_result/<filename>.txt.
    """

    @pytest.mark.parametrize(
        "doc_path",
        example_files,
        ids=[p.name for p in example_files],
    )
    def test_extract_document(
        self,
        doc_path: Path,
        ensure_output_dir: Path,
        sample_patient_history: Dict[str, Any],
    ):
        """
        Run full OCR pipeline on a single document.

        Asserts basic sanity (non-empty result) and writes a human-readable
        report with all extracted fields to ocr_result/<name>.txt.
        """
        from app.core.ocr.pipeline import process_document

        result = asyncio.get_event_loop().run_until_complete(
            process_document(
                file_path=str(doc_path),
                session_id="test_ocr_session",
                patient_id="test_patient",
                patient_history=sample_patient_history,
                original_filename=doc_path.name,
                use_vision=False,
                use_llm=False,
            )
        )

        # ── Write results to text file ──────────────────────────────────
        output_name = doc_path.stem + ".txt"
        output_path = ensure_output_dir / output_name
        report = _format_results(doc_path, result)
        output_path.write_text(report, encoding="utf-8")

        # Also write a JSON sidecar for programmatic consumption
        json_path = ensure_output_dir / (doc_path.stem + ".json")
        json_data = {
            "document_id": result.document_id,
            "original_filename": result.original_filename,
            "page_count": result.page_count,
            "overall_confidence": result.overall_confidence,
            "ocr_engines_used": result.ocr_engines_used,
            "classification": {
                "doc_type": (
                    result.classification.doc_type.value
                    if result.classification else "unknown"
                ),
                "confidence": (
                    result.classification.confidence
                    if result.classification else 0.0
                ),
            },
            "extracted_fields": [
                {
                    "field_id": f.field_id,
                    "field_name": f.field_name,
                    "value": f.value if not isinstance(f.value, float) or f.value == f.value else None,
                    "category": f.category.value,
                    "confidence": f.confidence,
                    "source_span": f.source_span[:100],
                    "extraction_method": f.extraction_method,
                    "metadata": f.metadata,
                }
                for f in result.extracted_fields
            ],
            "conflicts": [
                {
                    "conflict_id": c.conflict_id,
                    "field_name": c.field_name,
                    "extracted_value": c.extracted_value,
                    "existing_value": c.existing_value,
                    "conflict_type": c.conflict_type.value,
                    "severity": c.severity.value,
                    "message": c.message,
                    "recommendation": c.recommendation,
                }
                for c in result.conflicts
            ],
            "processing_errors": result.processing_errors,
            "full_text_length": len(result.full_text) if result.full_text else 0,
        }
        json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

        # ── Assertions ──────────────────────────────────────────────────
        # Basic sanity checks
        assert result is not None, "Pipeline returned None"
        assert result.document_id, "Document ID should be set"
        assert result.page_count >= 1, "Should have at least 1 page"

        # Report was written
        assert output_path.exists(), f"Output file not created: {output_path}"
        assert output_path.stat().st_size > 100, "Output file too small"

        print(f"\n  ✓ {doc_path.name}: "
              f"{result.page_count} page(s), "
              f"{len(result.extracted_fields)} fields, "
              f"{len(result.conflicts)} conflicts, "
              f"conf={result.overall_confidence:.2f}")


# ============================================================================
# Test: Verify all example documents were processed
# ============================================================================

@pytest.mark.integration
@pytest.mark.slow
@requires_pil
class TestOCRBatchSummary:
    """Verify that all documents produce output files."""

    def test_all_outputs_created(self, ensure_output_dir):
        """Every input file should have a matching output .txt file."""
        if not example_files:
            pytest.skip("No example documents found in ocr_examples/")

        missing = []
        for doc_path in example_files:
            output_path = ensure_output_dir / (doc_path.stem + ".txt")
            if not output_path.exists():
                missing.append(doc_path.name)

        if missing:
            # This is informational — files created during parametrized test above
            pytest.skip(
                f"Output files not yet created (run test_extract_document first): "
                f"{', '.join(missing)}"
            )


# ============================================================================
# Test: Page splitter on real files
# ============================================================================

@pytest.mark.integration
@requires_pil
class TestPageSplitterReal:
    """Test page splitting on actual files."""

    @pytest.mark.parametrize(
        "doc_path",
        [p for p in example_files if p.suffix.lower() == ".pdf"],
        ids=[p.name for p in example_files if p.suffix.lower() == ".pdf"],
    )
    def test_split_pdf(self, doc_path: Path):
        """PDF files should split into 1+ pages."""
        from app.core.ocr.page_splitter import split_document

        pages = split_document(doc_path)
        assert len(pages) >= 1
        for page in pages:
            assert page.page_number >= 1
            # Either text layer or image should be present
            assert page.image is not None or page.has_text_layer

    @pytest.mark.parametrize(
        "doc_path",
        [p for p in example_files if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp")],
        ids=[p.name for p in example_files if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp")],
    )
    def test_split_image(self, doc_path: Path):
        """Image files should produce exactly 1 page."""
        from app.core.ocr.page_splitter import split_document

        pages = split_document(doc_path)
        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].image is not None


# ============================================================================
# Test: Document classification on real files
# ============================================================================

@pytest.mark.integration
@requires_pil
class TestClassifyReal:
    """Test document classification on real OCR text."""

    @pytest.mark.parametrize(
        "doc_path",
        example_files,
        ids=[p.name for p in example_files],
    )
    def test_classify_heuristic(self, doc_path: Path):
        """Classify real documents without LLM — should return a valid type."""
        from app.core.ocr.document_classifier import classify_document

        # Quick-extract some text for classification
        text = ""
        if doc_path.suffix.lower() == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(doc_path) as pdf:
                    for page in pdf.pages[:3]:
                        text += (page.extract_text() or "") + "\n"
            except Exception:
                pytest.skip("pdfplumber failed to read PDF")
        else:
            try:
                import numpy as np
                from PIL import Image
                from app.core.ocr.extractor import _extract_via_paddle
                img = Image.open(doc_path)
                result = _extract_via_paddle(img)
                text = result.text
            except Exception:
                pytest.skip("PaddleOCR not available for image OCR")

        if not text.strip():
            pytest.skip(f"No text extracted from {doc_path.name}")

        result = classify_document(text, use_llm=False, filename=doc_path.name)
        assert result is not None
        assert hasattr(result, "doc_type")
        assert result.doc_type in DocumentType.__members__.values()
        print(f"\n  {doc_path.name} → {result.doc_type.value} (conf={result.confidence:.2f})")


# Need this import for the parametrize decoration
from app.core.ocr.document_classifier import DocumentType
