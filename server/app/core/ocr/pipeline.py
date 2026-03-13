"""
Master OCR pipeline orchestrator.

Chains all 10 stages of the medical document understanding pipeline:

  1. Page splitting
  2. Image preprocessing
  3. Layout detection
  4. Handwriting detection
  5. Multi-engine OCR extraction
  6. Text normalization
  7. Document classification
  8. Structured field extraction (medical NLP + LLM)
  9. Conflict detection
  10. Result packaging (DocumentArtifact + queue items)

Usage::

    from app.core.ocr.pipeline import process_document

    result = await process_document(
        file_path="storage/uploads/session123/scan.pdf",
        session_id="session123",
        patient_id="patient456",
    )
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .page_splitter import PageResult, split_document
from .preprocessor import preprocess_image
from .layout_detector import LayoutRegion, RegionType, detect_layout
from .handwriting_detector import classify_text_regions
from .extractor import OCRResult, extract_page_text, extract_text_from_region
from .normalizer import normalize_ocr_text
from .document_classifier import DocumentClassification, DocumentType, classify_document
from .field_extractor import ExtractedField, extract_fields
from .conflict_detector import ConflictItem, detect_conflicts

logger = logging.getLogger(__name__)


@dataclass
class PageProcessingResult:
    """Result from processing a single page."""
    page_number: int
    raw_text: str = ""
    normalized_text: str = ""
    confidence: float = 0.0
    regions: List[LayoutRegion] = field(default_factory=list)
    ocr_engine: str = ""


@dataclass
class DocumentProcessingResult:
    """Complete result from the OCR pipeline."""
    document_id: str = ""
    file_path: str = ""
    original_filename: str = ""

    # Stage outputs
    page_count: int = 0
    full_text: str = ""
    classification: Optional[DocumentClassification] = None
    extracted_fields: List[ExtractedField] = field(default_factory=list)
    conflicts: List[ConflictItem] = field(default_factory=list)

    # Per-page details
    pages: List[PageProcessingResult] = field(default_factory=list)

    # Aggregate metrics
    overall_confidence: float = 0.0
    ocr_engines_used: List[str] = field(default_factory=list)
    processing_errors: List[str] = field(default_factory=list)

    # For pipeline integration
    document_artifact: Optional[Dict[str, Any]] = None
    candidate_facts: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.document_id:
            self.document_id = f"doc_{uuid.uuid4().hex[:12]}"


async def process_document(
    file_path: str | Path,
    *,
    session_id: str = "",
    patient_id: str = "",
    patient_history: Optional[Dict[str, Any]] = None,
    original_filename: Optional[str] = None,
    use_vision: bool = False,
    use_llm: bool = True,
    confidence_threshold: float = 0.5,
) -> DocumentProcessingResult:
    """
    Run the full 10-stage OCR pipeline on a medical document.

    Parameters
    ----------
    file_path : str or Path
        Path to the uploaded document file.
    session_id : str
        Current session ID (for provenance tracking).
    patient_id : str
        Patient ID (for conflict detection against history).
    patient_history : dict, optional
        Pre-loaded patient history from PatientService.
    original_filename : str, optional
        Original upload filename (used for classification hints).
    use_vision : bool
        Use Groq vision API for layout detection and handwriting OCR.
    use_llm : bool
        Use Groq LLM for classification and field extraction.
    confidence_threshold : float
        Fields below this are flagged as low-confidence conflicts.

    Returns
    -------
    DocumentProcessingResult
    """
    file_path = Path(file_path)
    result = DocumentProcessingResult(
        file_path=str(file_path),
        original_filename=original_filename or file_path.name,
    )

    if not file_path.exists():
        result.processing_errors.append(f"File not found: {file_path}")
        return result

    logger.info("OCR pipeline starting for: %s", file_path.name)

    # ── Stage 1: Page Splitting ─────────────────────────────────────────
    try:
        pages = split_document(file_path)
        result.page_count = len(pages)
    except Exception as e:
        result.processing_errors.append(f"Page splitting failed: {e}")
        logger.error("Page splitting failed: %s", e)
        return result

    if not pages:
        result.processing_errors.append("No pages extracted from document")
        return result

    logger.info("Split into %d pages", len(pages))

    # ── Stages 2-5: Per-page processing (preprocess → layout → OCR) ────
    page_results: List[PageProcessingResult] = []
    all_text_parts: List[str] = []
    all_confidences: List[float] = []
    engines_used: set = set()

    # Process pages (could be parallelized with asyncio.gather for large docs)
    for page in pages:
        page_result = _process_single_page(
            page,
            use_vision=use_vision,
        )
        page_results.append(page_result)

        if page_result.normalized_text:
            all_text_parts.append(page_result.normalized_text)
        if page_result.confidence > 0:
            all_confidences.append(page_result.confidence)
        if page_result.ocr_engine:
            engines_used.update(page_result.ocr_engine.split(","))

    result.pages = page_results
    result.full_text = "\n\n".join(all_text_parts)
    result.overall_confidence = (
        sum(all_confidences) / len(all_confidences)
        if all_confidences else 0.0
    )
    result.ocr_engines_used = sorted(engines_used)

    if not result.full_text.strip():
        result.processing_errors.append("No text extracted from any page")
        return result

    logger.info(
        "OCR complete: %d chars, avg confidence %.2f, engines: %s",
        len(result.full_text),
        result.overall_confidence,
        result.ocr_engines_used,
    )

    # ── Stage 7: Document Classification ────────────────────────────────
    try:
        result.classification = classify_document(
            result.full_text,
            use_llm=use_llm,
            filename=original_filename,
        )
        logger.info(
            "Document classified as: %s (confidence %.2f)",
            result.classification.doc_type.value,
            result.classification.confidence,
        )
    except Exception as e:
        result.processing_errors.append(f"Classification failed: {e}")
        result.classification = DocumentClassification(doc_type=DocumentType.UNKNOWN)

    # ── Stage 8: Structured Field Extraction ────────────────────────────
    try:
        result.extracted_fields = extract_fields(
            result.full_text,
            doc_type=(result.classification.doc_type if result.classification else DocumentType.UNKNOWN),
            ocr_confidence=result.overall_confidence,
            source_document=result.original_filename,
            use_llm=use_llm,
        )
        logger.info("Extracted %d fields", len(result.extracted_fields))
    except Exception as e:
        result.processing_errors.append(f"Field extraction failed: {e}")
        logger.error("Field extraction failed: %s", e)

    # ── Stage 9: Conflict Detection ─────────────────────────────────────
    try:
        result.conflicts = detect_conflicts(
            result.extracted_fields,
            patient_history=patient_history,
            confidence_threshold=confidence_threshold,
        )
        logger.info("Detected %d conflicts", len(result.conflicts))
    except Exception as e:
        result.processing_errors.append(f"Conflict detection failed: {e}")
        logger.error("Conflict detection failed: %s", e)

    # ── Stage 10: Package for pipeline integration ──────────────────────
    result.document_artifact = _build_document_artifact(result)
    result.candidate_facts = _build_candidate_facts(result.extracted_fields)

    logger.info(
        "OCR pipeline complete for %s: %d fields, %d conflicts, type=%s",
        file_path.name,
        len(result.extracted_fields),
        len(result.conflicts),
        result.classification.doc_type.value if result.classification else "unknown",
    )

    return result


# ── Internal helpers ────────────────────────────────────────────────────────

def _process_single_page(
    page: PageResult,
    *,
    use_vision: bool = False,
) -> PageProcessingResult:
    """
    Process a single page through stages 2-6:
    preprocess → layout detect → handwriting classify → OCR → normalize.
    """
    pr = PageProcessingResult(page_number=page.page_number)

    # If we already have a good text layer, use it (Stage 2 shortcut)
    if page.has_text_layer and page.text_layer:
        raw_text = page.text_layer
        pr.raw_text = raw_text
        pr.confidence = 0.95
        pr.ocr_engine = "text_layer"

        # Still do layout detection on the text
        try:
            pr.regions = detect_layout(
                raw_text,
                tables=page.tables if hasattr(page, "tables") else None,
                page_image=page.image,
                use_vision=use_vision,
            )
        except Exception as e:
            logger.debug("Layout detection failed for page %d: %s", page.page_number, e)

    else:
        # Need OCR — preprocess image first
        image = page.image
        if image is not None:
            try:
                image = preprocess_image(image)
            except Exception as e:
                logger.debug("Preprocessing failed for page %d: %s", page.page_number, e)

        # Layout detection (on existing text if any, or from image)
        try:
            existing_text = page.text_layer or ""
            pr.regions = detect_layout(
                existing_text,
                tables=page.tables if hasattr(page, "tables") else None,
                page_image=image,
                use_vision=use_vision,
            )
        except Exception as e:
            logger.debug("Layout detection failed for page %d: %s", page.page_number, e)

        # Handwriting classification
        if pr.regions:
            try:
                pr.regions = classify_text_regions(
                    pr.regions,
                    page_image=image,
                    use_vision=use_vision,
                )
            except Exception as e:
                logger.debug("Handwriting detection failed for page %d: %s", page.page_number, e)

        # Multi-engine OCR extraction
        try:
            ocr_result = extract_page_text(page, regions=pr.regions if pr.regions else None)
            pr.raw_text = ocr_result.text
            pr.confidence = ocr_result.confidence
            pr.ocr_engine = ocr_result.engine
        except Exception as e:
            logger.warning("OCR failed for page %d: %s", page.page_number, e)

    # Normalize text (Stage 6)
    if pr.raw_text:
        try:
            pr.normalized_text = normalize_ocr_text(pr.raw_text)
        except Exception:
            pr.normalized_text = pr.raw_text

    return pr


def _build_document_artifact(result: DocumentProcessingResult) -> Dict[str, Any]:
    """Build a DocumentArtifact dict matching state.py TypedDict."""
    return {
        "document_id": result.document_id,
        "source_type": _infer_source_type(result.file_path),
        "extracted_text": result.full_text,
        "tables": [],  # Could be populated from page-level table extraction
        "metadata": {
            "original_filename": result.original_filename,
            "page_count": result.page_count,
            "document_type": (
                result.classification.doc_type.value
                if result.classification else "unknown"
            ),
            "classification_confidence": (
                result.classification.confidence
                if result.classification else 0.0
            ),
            "overall_ocr_confidence": result.overall_confidence,
            "ocr_engines": result.ocr_engines_used,
            "field_count": len(result.extracted_fields),
            "conflict_count": len(result.conflicts),
            "detected_sections": (
                result.classification.detected_sections
                if result.classification else []
            ),
        },
    }


def _infer_source_type(file_path: str) -> str:
    """Infer DocumentArtifact source_type from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"):
        return "image"
    elif ext in (".txt", ".text"):
        return "text"
    return "unknown"


def _build_candidate_facts(
    fields: List[ExtractedField],
) -> List[Dict[str, Any]]:
    """Convert ExtractedFields to CandidateFact dicts matching state.py."""
    facts = []
    for f in fields:
        facts.append({
            "fact_id": f.field_id,
            "type": f.category.value,
            "value": {
                "field_name": f.field_name,
                "extracted_value": f.value,
                **(f.metadata or {}),
            },
            "provenance": {
                "source_document": f.source_document,
                "source_span": f.source_span,
                "extraction_method": f.extraction_method,
            },
            "confidence": f.confidence,
        })
    return facts
