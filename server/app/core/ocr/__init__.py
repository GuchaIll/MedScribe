"""
OCR pipeline for medical document ingestion.

Sub-modules:
  - preprocessor         : image cleanup / deskew / binarise before OCR
  - extractor            : multi-engine text extraction (RapidOCR/PaddleOCR models + Groq vision)
  - normalizer           : post-OCR text normalisation (medical abbreviations, whitespace)
  - page_splitter        : split PDFs / images into per-page results
  - layout_detector      : detect document structure (headers, tables, KV pairs)
  - handwriting_detector : classify printed vs handwritten regions
  - document_classifier  : LLM-based document type classification
  - field_extractor      : structured medical field extraction (LLM + regex)
  - conflict_detector    : cross-reference extracted fields vs patient history
  - pipeline             : master orchestrator chaining all 10 stages

Usage::

    # Full pipeline (recommended)
    from app.core.ocr.pipeline import process_document
    result = await process_document("path/to/scan.pdf", session_id="s1", patient_id="p1")

    # Legacy per-file extraction (still supported)
    from app.core.ocr.extractor import extract_text_from_pdf, extract_text_from_image
    from app.core.ocr.normalizer import normalize_ocr_text
"""

# Legacy exports (backward compatible)
from .extractor import extract_text_from_pdf, extract_text_from_image
from .normalizer import normalize_ocr_text
from .preprocessor import preprocess_image

# New pipeline exports
from .page_splitter import split_document, PageResult
from .layout_detector import detect_layout, LayoutRegion, RegionType
from .handwriting_detector import classify_text_regions
from .document_classifier import classify_document, DocumentType, DocumentClassification
from .field_extractor import extract_fields, ExtractedField, FieldCategory
from .conflict_detector import detect_conflicts, ConflictItem, ConflictType, ConflictSeverity
from .pipeline import process_document, DocumentProcessingResult

__all__ = [
    # Legacy
    "extract_text_from_pdf",
    "extract_text_from_image",
    "normalize_ocr_text",
    "preprocess_image",
    # Page splitting
    "split_document",
    "PageResult",
    # Layout detection
    "detect_layout",
    "LayoutRegion",
    "RegionType",
    # Handwriting detection
    "classify_text_regions",
    # Document classification
    "classify_document",
    "DocumentType",
    "DocumentClassification",
    # Field extraction
    "extract_fields",
    "ExtractedField",
    "FieldCategory",
    # Conflict detection
    "detect_conflicts",
    "ConflictItem",
    "ConflictType",
    "ConflictSeverity",
    # Pipeline orchestrator
    "process_document",
    "DocumentProcessingResult",
]
