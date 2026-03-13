"""
Image pre-processing utilities for OCR.

Handles deskewing, binarisation, noise removal, and contrast
enhancement to improve downstream text extraction accuracy.

Provides two pipelines:
  - ``preprocess_image``      – Pillow-based (general purpose, legacy)
  - ``preprocess_for_paddle`` – OpenCV-based (MediScribe pattern, optimised
    for PaddleOCR: grayscale → denoise → adaptive threshold → dilate)

Dependencies:
  - Pillow (required)
  - numpy  (optional, for advanced transforms)
  - opencv-python-headless (optional, for ``preprocess_for_paddle``)
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional, Union

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:
    Image = None  # type: ignore[assignment,misc]

import logging

logger = logging.getLogger(__name__)


def preprocess_image(
    source: Union[str, Path, bytes, "Image.Image"],
    *,
    grayscale: bool = True,
    denoise: bool = True,
    enhance_contrast: bool = True,
    deskew: bool = False,
    target_dpi: int = 300,
) -> "Image.Image":
    """
    Apply a standardised preprocessing pipeline to *source* and return a
    ``PIL.Image`` ready for OCR extraction.

    Parameters
    ----------
    source:
        File path, raw bytes, or an already-loaded PIL Image.
    grayscale:
        Convert to greyscale (usually helps OCR).
    denoise:
        Apply a median filter to reduce scanning noise.
    enhance_contrast:
        Auto-contrast the image so text is sharper.
    deskew:
        Attempt to correct page rotation (requires numpy).
    target_dpi:
        Resample to this DPI if image metadata is available.

    Returns
    -------
    PIL.Image.Image
        The preprocessed image.
    """
    if Image is None:
        raise ImportError(
            "Pillow is required for image preprocessing. "
            "Install it with: pip install Pillow"
        )

    img = _load_image(source)

    if grayscale:
        img = img.convert("L")

    if denoise:
        img = img.filter(ImageFilter.MedianFilter(size=3))

    if enhance_contrast:
        img = ImageOps.autocontrast(img, cutoff=1)

    if deskew:
        img = _try_deskew(img)

    return img


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(source: Union[str, Path, bytes, Any]) -> "Image.Image":
    """Load an image from various source types."""
    if Image is None:
        raise ImportError("Pillow is required")

    if isinstance(source, (str, Path)):
        return Image.open(source)
    elif isinstance(source, bytes):
        return Image.open(io.BytesIO(source))
    elif hasattr(source, "mode"):
        # Likely a PIL Image already
        return source
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")


def _try_deskew(img: "Image.Image") -> "Image.Image":
    """
    Attempt to straighten a skewed scan.

    Uses numpy for angle detection when available, otherwise returns
    the image unchanged.
    """
    try:
        import numpy as np

        arr = np.array(img)

        # Simple projection-profile deskew:
        # find the rotation angle that minimises the variance of
        # row-wise pixel sums (works well for text pages).
        best_angle = 0.0
        best_score = float("inf")

        for angle in [a * 0.5 for a in range(-10, 11)]:
            rotated = img.rotate(angle, expand=False, fillcolor=255)
            profile = np.array(rotated).sum(axis=1).astype(float)
            score = float(np.diff(profile).var())
            if score < best_score:
                best_score = score
                best_angle = angle

        if abs(best_angle) > 0.1:
            logger.info("Deskew: rotating %.1f°", best_angle)
            img = img.rotate(best_angle, expand=True, fillcolor=255)

    except ImportError:
        logger.debug("numpy not available; skipping deskew")

    return img


# ---------------------------------------------------------------------------
# MediScribe-style OpenCV preprocessing for PaddleOCR
# ---------------------------------------------------------------------------

def preprocess_for_paddle(
    source: Union[str, Path, bytes, "Image.Image"],
) -> "Image.Image":
    """
    Apply the MediScribe 5-step OpenCV preprocessing pipeline optimised
    for PaddleOCR on medical documents.

    Steps:
      1. Convert to grayscale
      2. Denoise (``cv2.fastNlMeansDenoising``)
      3. Adaptive threshold (Gaussian, blockSize=11, C=2)
      4. Dilate (3×3 kernel, 1 iteration — connects broken text strokes)
      5. Convert back to PIL Image

    Falls back to ``preprocess_image`` if OpenCV is not available.

    Parameters
    ----------
    source:
        File path, raw bytes, or an already-loaded PIL Image.

    Returns
    -------
    PIL.Image.Image
        The preprocessed image ready for PaddleOCR.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.debug("OpenCV not available; falling back to Pillow preprocessing")
        return preprocess_image(source, grayscale=True, denoise=True, enhance_contrast=True)

    if Image is None:
        raise ImportError("Pillow is required for image preprocessing.")

    # Load to PIL first, then convert to numpy for OpenCV
    img = _load_image(source)
    img_array = np.array(img)

    # Step 1: grayscale
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # Step 2: denoise
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

    # Step 3: adaptive threshold (Gaussian, blockSize=11, C=2 — MediScribe params)
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )

    # Step 4: dilate (connects broken strokes in handwritten / degraded text)
    kernel = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    # Step 5: convert back to PIL
    return Image.fromarray(dilated)
