"""
OCR Reader Tool — extracts text from medical documents (PDFs, images).

Wraps the ``app.core.ocr`` pipeline to provide a simple interface for
agent nodes that need to ingest scanned medical records.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


class OCRReaderTool:
    """
    Tool for extracting text and tables from medical documents.

    Delegates to ``app.core.ocr`` sub-modules for preprocessing,
    extraction, and normalisation.
    """

    def read_pdf(self, file_path: str | Path) -> Dict[str, Any]:
        """
        Extract text from a PDF file.

        Returns:
            Dict with keys: text, tables, page_count, metadata.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"text": "", "tables": [], "page_count": 0, "error": "File not found"}

        try:
            from app.core.ocr.extractor import extract_text_from_pdf
            result = extract_text_from_pdf(file_path)
            return result
        except ImportError:
            # Fallback to basic PDF text extraction
            return self._fallback_pdf_read(file_path)
        except Exception as e:
            return {"text": "", "tables": [], "page_count": 0, "error": str(e)}

    def read_image(self, file_path: str | Path) -> Dict[str, Any]:
        """
        Extract text from a scanned image.

        Returns:
            Dict with keys: text, confidence, metadata.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"text": "", "confidence": 0.0, "error": "File not found"}

        try:
            from app.core.ocr.extractor import extract_text_from_image
            return extract_text_from_image(file_path)
        except ImportError:
            return {"text": "", "confidence": 0.0, "error": "OCR extractor not installed"}
        except Exception as e:
            return {"text": "", "confidence": 0.0, "error": str(e)}

    def read_document(self, file_path: str | Path) -> Dict[str, Any]:
        """
        Auto-detect document type and extract text.
        """
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            return self.read_pdf(file_path)
        elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            return self.read_image(file_path)
        elif suffix == ".txt":
            return {"text": file_path.read_text(encoding="utf-8"), "tables": []}
        else:
            return {"text": "", "error": f"Unsupported format: {suffix}"}

    @staticmethod
    def _fallback_pdf_read(file_path: Path) -> Dict[str, Any]:
        """Basic PDF text extraction using app.utils.pdf_extractor."""
        try:
            from app.utils.pdf_extractor import extract_text
            text = extract_text(str(file_path))
            return {"text": text, "tables": [], "page_count": 0}
        except Exception as e:
            return {"text": "", "tables": [], "page_count": 0, "error": str(e)}
