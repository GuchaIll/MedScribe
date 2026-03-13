"""
Page splitter for multi-page medical documents.

Splits PDFs into per-page images and detects whether pages have
native text layers (searchable) or need OCR (scanned).

Dependencies:
  - pdfplumber (required)
  - pdf2image  (required for scanned PDFs — needs Poppler binaries)
  - Pillow     (required)
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]


@dataclass
class PageResult:
    """Result from splitting a single page."""
    page_number: int
    image: Optional[object] = None           # PIL.Image.Image
    text_layer: str = ""                     # Native text (empty if scanned)
    has_text_layer: bool = False             # True if PDF page has extractable text
    tables: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def split_document(
    file_path: Union[str, Path],
    *,
    target_dpi: int = 300,
    detect_text_layer: bool = True,
) -> List[PageResult]:
    """
    Split a document into per-page results.

    For PDFs:
      - Extracts native text layer per page via pdfplumber
      - Converts each page to an image via pdf2image
      - Flags pages that have searchable text (can skip OCR)

    For images (PNG, JPG, TIFF, BMP):
      - Single-page: returns one PageResult with the image
      - Multi-frame TIFF: splits into separate frames

    Parameters
    ----------
    file_path : str | Path
        Path to the document file.
    target_dpi : int
        DPI for PDF-to-image conversion. Higher = better OCR, slower.
    detect_text_layer : bool
        If True, attempt to extract native text from PDF pages.

    Returns
    -------
    List[PageResult]
        One entry per page.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        return []

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _split_pdf(file_path, target_dpi=target_dpi, detect_text_layer=detect_text_layer)
    elif suffix in (".tif", ".tiff"):
        return _split_tiff(file_path)
    elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return _split_single_image(file_path)
    else:
        logger.warning("Unsupported file type: %s", suffix)
        return []


def _split_pdf(
    file_path: Path,
    *,
    target_dpi: int = 300,
    detect_text_layer: bool = True,
) -> List[PageResult]:
    """Split PDF into per-page images + optional text layer extraction."""
    pages: List[PageResult] = []

    # ── Step 1: Extract native text layer per page ──────────────────────
    text_layers: List[dict] = []
    if detect_text_layer:
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = (page.extract_text() or "").strip()
                    tables = page.extract_tables() or []
                    text_layers.append({
                        "text": text,
                        "tables": tables,
                        "has_text": len(text) > 20,  # Meaningful text threshold
                    })
        except ImportError:
            logger.warning("pdfplumber not installed; skipping text layer detection")
        except Exception as e:
            logger.warning("pdfplumber text extraction failed: %s", e)

    # ── Step 2: Convert pages to images ─────────────────────────────────
    page_images: List = []
    try:
        from pdf2image import convert_from_path
        page_images = convert_from_path(
            str(file_path),
            dpi=target_dpi,
            fmt="png",
            thread_count=2,
        )
    except ImportError:
        logger.warning(
            "pdf2image not installed. Scanned PDF pages cannot be converted "
            "to images for OCR. Install with: pip install pdf2image"
        )
    except Exception as e:
        logger.warning("PDF-to-image conversion failed: %s", e)

    # ── Step 3: Combine text layers + images ────────────────────────────
    page_count = max(len(text_layers), len(page_images))

    for i in range(page_count):
        tl = text_layers[i] if i < len(text_layers) else {"text": "", "tables": [], "has_text": False}
        img = page_images[i] if i < len(page_images) else None

        pages.append(PageResult(
            page_number=i + 1,
            image=img,
            text_layer=tl["text"],
            has_text_layer=tl["has_text"],
            tables=tl["tables"],
            metadata={"source": str(file_path), "dpi": target_dpi},
        ))

    logger.info(
        "Split PDF %s: %d pages (%d with text layer, %d need OCR)",
        file_path.name,
        len(pages),
        sum(1 for p in pages if p.has_text_layer),
        sum(1 for p in pages if not p.has_text_layer),
    )
    return pages


def _split_tiff(file_path: Path) -> List[PageResult]:
    """Split multi-frame TIFF into separate page results."""
    if Image is None:
        logger.error("Pillow not installed; cannot process TIFF")
        return []

    pages: List[PageResult] = []
    try:
        img = Image.open(file_path)
        frame = 0
        while True:
            try:
                img.seek(frame)
                # Copy frame to detach from file handle
                frame_img = img.copy()
                pages.append(PageResult(
                    page_number=frame + 1,
                    image=frame_img,
                    metadata={"source": str(file_path), "frame": frame},
                ))
                frame += 1
            except EOFError:
                break
    except Exception as e:
        logger.error("TIFF splitting failed: %s", e)

    logger.info("Split TIFF %s: %d frames", file_path.name, len(pages))
    return pages


def _split_single_image(file_path: Path) -> List[PageResult]:
    """Wrap a single image as one page result."""
    if Image is None:
        logger.error("Pillow not installed; cannot process image")
        return []

    try:
        img = Image.open(file_path)
        return [PageResult(
            page_number=1,
            image=img,
            metadata={"source": str(file_path), "size": img.size},
        )]
    except Exception as e:
        logger.error("Image loading failed: %s", e)
        return []
