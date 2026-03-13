"""
Text and table extraction from medical documents.

Supports three extraction modes:
  1. **File-level** – ``extract_text_from_pdf`` / ``extract_text_from_image``
     (legacy convenience wrappers).
  2. **Region-level** – ``extract_text_from_region``  dispatches to the best
     OCR engine per region type (printed → PaddleOCR, handwritten → Groq
     vision, table → pdfplumber).
  3. **Page-level** – ``extract_page_text``  runs all regions on a
     ``PageResult`` and returns merged text with confidence.

Dependencies installed optionally:
  - pdfplumber / PyPDF2 for PDFs
  - rapidocr-onnxruntime for image OCR (PaddleOCR models via ONNX, no system binary needed)
  - groq for vision-based handwriting OCR
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .preprocessor import preprocess_image, preprocess_for_paddle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RapidOCR lazy singleton  (PaddleOCR models via ONNX Runtime)
# ---------------------------------------------------------------------------
_rapid_ocr_instance = None


def _get_paddle_ocr():
    """
    Return a lazily-initialised RapidOCR instance.

    RapidOCR runs the same PaddleOCR detection/recognition models through
    ONNX Runtime instead of PaddlePaddle, which avoids version-
    compatibility issues on Windows/Python 3.13+.

    Uses the default PaddleOCR model set (det_v4 + rec_v4 + cls) which
    is bundled with the rapidocr-onnxruntime wheel.
    """
    global _rapid_ocr_instance
    if _rapid_ocr_instance is not None:
        return _rapid_ocr_instance

    try:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_ocr_instance = RapidOCR()
        return _rapid_ocr_instance
    except ImportError:
        logger.error("rapidocr-onnxruntime is not installed.  pip install rapidocr-onnxruntime")
        return None
    except Exception as e:
        logger.error("Failed to initialise RapidOCR: %s", e)
        return None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OCRResult:
    """Result from any extraction engine."""
    text: str = ""
    confidence: float = 0.0
    engine: str = "unknown"
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Region-level extraction  (NEW — multi-engine dispatch)
# ---------------------------------------------------------------------------

def extract_text_from_region(
    image: Optional[object] = None,
    region: Optional[object] = None,
    *,
    force_engine: Optional[str] = None,
) -> OCRResult:
    """
    Extract text from a single layout region using the best engine.

    Parameters
    ----------
    image : PIL.Image
        The page image (or cropped region image).
    region : LayoutRegion, optional
        Region metadata (type, text_type, bounding_box).  When provided
        the engine is chosen automatically.
    force_engine : str, optional
        Override engine selection: ``"paddleocr"``, ``"vision"``, or
        ``"text_layer"`` (for text already extracted by pdfplumber).

    Returns
    -------
    OCRResult
    """
    from .layout_detector import RegionType, TextType

    # If the region already has text from the text layer, use it directly
    if region is not None and getattr(region, "text", "").strip():
        text_layer_result = OCRResult(
            text=region.text.strip(),
            confidence=getattr(region, "confidence", 0.9),
            engine="text_layer",
        )
        if force_engine == "text_layer":
            return text_layer_result

        # For printed text with text layer, trust it
        if (
            force_engine is None
            and getattr(region, "text_type", None) == TextType.PRINTED
        ):
            return text_layer_result

    engine = force_engine
    if engine is None and region is not None:
        text_type = getattr(region, "text_type", TextType.PRINTED)
        region_type = getattr(region, "region_type", RegionType.PARAGRAPH)

        if text_type == TextType.HANDWRITTEN or region_type == RegionType.SIGNATURE:
            engine = "vision"
        elif region_type == RegionType.TABLE:
            engine = "paddleocr"  # Tables use PaddleOCR; pdfplumber tables handled separately
        else:
            engine = "paddleocr"

    if engine is None:
        engine = "paddleocr"

    if engine == "vision":
        result = _extract_via_vision(image)
        # Also get PaddleOCR result as alternative
        alt = _extract_via_paddle(image)
        if alt.text:
            result.alternatives.append({"text": alt.text, "confidence": alt.confidence, "engine": "paddleocr"})
        return result

    return _extract_via_paddle(image)


def _extract_via_paddle(image: Optional[object]) -> OCRResult:
    """
    Run PaddleOCR on an image using the MediScribe multi-pass strategy.

    Three passes are attempted in order:
      1. Preprocessed image  (grayscale, denoise, adaptive threshold)
      2. Original image      (as-is)
      3. Inverted image      (bitwise_not — good for dark backgrounds)

    The pass that yields the most text wins.
    """
    if image is None:
        return OCRResult(error="No image provided")

    ocr = _get_paddle_ocr()
    if ocr is None:
        return OCRResult(error="RapidOCR not available. pip install rapidocr-onnxruntime")

    try:
        return _run_multi_pass_paddle(image, ocr)
    except Exception as e:
        logger.warning("PaddleOCR extraction failed: %s", e)
        return OCRResult(error=str(e))


def _run_multi_pass_paddle(image: object, ocr: object) -> OCRResult:
    """
    Execute the MediScribe 3-pass OCR strategy and return the best result.

    Each pass converts the PIL Image to a numpy array, runs RapidOCR
    (PaddleOCR models via ONNX), and the pass with the longest extracted
    text is used.
    """
    import numpy as np

    # Prepare PIL images for each pass
    passes: list[tuple[str, object]] = []

    # Pass 1: preprocessed (MediScribe-style: grayscale + denoise + adaptive threshold)
    try:
        preprocessed = preprocess_for_paddle(image)
        passes.append(("preprocessed", preprocessed))
    except Exception as e:
        logger.debug("Preprocessing failed, skipping pass 1: %s", e)

    # Pass 2: original image
    passes.append(("original", image))

    # Pass 3: inverted image (bitwise_not)
    try:
        from PIL import ImageOps
        if hasattr(image, "mode"):
            inv_img = image.convert("L") if image.mode != "L" else image
            inverted = ImageOps.invert(inv_img)
            passes.append(("inverted", inverted))
    except Exception as e:
        logger.debug("Inversion failed, skipping pass 3: %s", e)

    best_text = ""
    best_conf = 0.0
    best_pass = "unknown"

    for pass_name, pass_img in passes:
        try:
            # Convert PIL Image to numpy array for RapidOCR
            img_array = np.array(pass_img)
            result, _elapse = ocr(img_array)

            if not result:
                continue

            lines: list[str] = []
            confidences: list[float] = []

            for line_info in result:
                # RapidOCR format: [bbox, text, confidence_string]
                if len(line_info) >= 3:
                    text_part = str(line_info[1])
                    conf_part = float(line_info[2])
                    lines.append(text_part)
                    confidences.append(conf_part)

            text = "\n".join(lines)
            avg_conf = sum(confidences) / max(len(confidences), 1)

            # Keep the pass that produces the most text
            if len(text) > len(best_text):
                best_text = text
                best_conf = avg_conf
                best_pass = pass_name

        except Exception as e:
            logger.debug("PaddleOCR pass '%s' failed: %s", pass_name, e)
            continue

    if not best_text:
        return OCRResult(text="", confidence=0.0, engine="paddleocr", error="No text extracted in any pass")

    return OCRResult(
        text=best_text.strip(),
        confidence=round(best_conf * 100, 2),  # Normalise to 0-100 scale
        engine="paddleocr",
    )


def _extract_via_vision(image: Optional[object]) -> OCRResult:
    """Use Groq vision API to extract handwritten text from an image."""
    if image is None:
        return OCRResult(error="No image provided")

    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq not installed; falling back to PaddleOCR")
        return _extract_via_paddle(image)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return _extract_via_paddle(image)

    try:
        buf = io.BytesIO()
        if hasattr(image, "save"):
            image.save(buf, format="PNG")
        else:
            return _extract_via_paddle(image)

        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Read ALL text in this medical document image, "
                            "including handwritten portions. Output ONLY the "
                            "extracted text, preserving line breaks. "
                            "Do not add commentary."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }],
            max_tokens=2000,
            temperature=0.1,
        )

        text = response.choices[0].message.content.strip()
        return OCRResult(text=text, confidence=0.75, engine="groq_vision")

    except Exception as e:
        logger.warning("Vision OCR failed: %s; falling back to PaddleOCR", e)
        return _extract_via_paddle(image)


# ---------------------------------------------------------------------------
# Page-level extraction  (NEW)
# ---------------------------------------------------------------------------

def extract_page_text(
    page_result: object,
    regions: Optional[List[object]] = None,
) -> OCRResult:
    """
    Extract all text from a page, using region-aware engine dispatch.

    Parameters
    ----------
    page_result : PageResult
        From page_splitter.
    regions : list of LayoutRegion, optional
        Layout regions.  When provided each region is OCR'd with the
        appropriate engine and results are merged.

    Returns
    -------
    OCRResult
        Merged text from all regions with weighted confidence.
    """
    # If we have text from the text layer and no regions, use it directly
    if not regions and hasattr(page_result, "text_layer") and page_result.text_layer:
        return OCRResult(
            text=page_result.text_layer.strip(),
            confidence=0.95,
            engine="text_layer",
        )

    if not regions:
        # Fall back to full-page PaddleOCR
        image = getattr(page_result, "image", None)
        return _extract_via_paddle(image)

    # Extract each region and merge
    texts: List[str] = []
    confs: List[float] = []
    engines: List[str] = []

    for region in regions:
        result = extract_text_from_region(
            image=getattr(page_result, "image", None),
            region=region,
        )
        if result.text:
            texts.append(result.text)
            confs.append(result.confidence)
            engines.append(result.engine)

    if not texts:
        return OCRResult(text="", confidence=0.0, engine="none")

    merged_text = "\n".join(texts)
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    return OCRResult(
        text=merged_text,
        confidence=round(avg_conf, 2),
        engine=",".join(set(engines)),
    )


# ---------------------------------------------------------------------------
# File-level extraction  (LEGACY — preserved for backward compat)
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_path: Path | str) -> Dict[str, Any]:
    """
    Extract text (and optionally tables) from a PDF.

    Tries *pdfplumber* first (better table support), then falls back to
    *PyPDF2* for plain text extraction.

    Returns
    -------
    dict
        ``text``: concatenated page text,
        ``tables``: list of extracted tables (list-of-lists),
        ``page_count``: number of pages,
        ``metadata``: PDF metadata dict.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return _empty_pdf_result(error="File not found")

    # Attempt 1: pdfplumber (rich extraction)
    result = _try_pdfplumber(file_path)
    if result is not None:
        return result

    # Attempt 2: PyPDF2 (plain text only)
    result = _try_pypdf2(file_path)
    if result is not None:
        return result

    return _empty_pdf_result(
        error="No PDF library available. Install pdfplumber or PyPDF2."
    )


def extract_text_from_image(file_path: Path | str) -> Dict[str, Any]:
    """
    Run OCR on a scanned image to extract text.

    The image is preprocessed then sent through the PaddleOCR multi-pass
    strategy (preprocessed → original → inverted).

    Returns
    -------
    dict
        ``text``: recognised text string,
        ``confidence``: average character confidence (0–100),
        ``metadata``: dict with image size.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return {"text": "", "confidence": 0.0, "error": "File not found"}

    ocr = _get_paddle_ocr()
    if ocr is None:
        return {
            "text": "",
            "confidence": 0.0,
            "error": "RapidOCR not available. pip install rapidocr-onnxruntime",
        }

    try:
        from PIL import Image
        img = Image.open(file_path)
        result = _extract_via_paddle(img)

        return {
            "text": result.text,
            "confidence": result.confidence,
            "metadata": {
                "image_size": img.size if hasattr(img, "size") else None,
            },
        }
    except Exception as e:
        logger.exception("OCR image extraction failed")
        return {"text": "", "confidence": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_pdfplumber(file_path: Path) -> Optional[Dict[str, Any]]:
    """Extract using pdfplumber if available."""
    try:
        import pdfplumber
    except ImportError:
        return None

    try:
        text_parts: List[str] = []
        tables: List[List[List[str]]] = []

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            metadata = pdf.metadata or {}

            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

                page_tables = page.extract_tables() or []
                tables.extend(page_tables)

        return {
            "text": "\n\n".join(text_parts).strip(),
            "tables": tables,
            "page_count": page_count,
            "metadata": dict(metadata),
        }
    except Exception as e:
        logger.warning("pdfplumber extraction failed: %s", e)
        return None


def _try_pypdf2(file_path: Path) -> Optional[Dict[str, Any]]:
    """Extract using PyPDF2 if available."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(str(file_path))
        text_parts = [
            page.extract_text() or "" for page in reader.pages
        ]
        metadata = reader.metadata
        return {
            "text": "\n\n".join(text_parts).strip(),
            "tables": [],
            "page_count": len(reader.pages),
            "metadata": dict(metadata) if metadata else {},
        }
    except Exception as e:
        logger.warning("PyPDF2 extraction failed: %s", e)
        return None


def _empty_pdf_result(*, error: str = "") -> Dict[str, Any]:
    """Return a well-typed empty result dict."""
    result: Dict[str, Any] = {
        "text": "",
        "tables": [],
        "page_count": 0,
    }
    if error:
        result["error"] = error
    return result
