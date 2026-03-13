"""
Handwriting detection for medical documents.

Classifies text regions as printed, handwritten, or mixed.
Uses heuristic analysis by default with optional LLM vision fallback.

Medical documents commonly have handwritten annotations on printed forms,
which require different OCR engines for optimal extraction.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .layout_detector import LayoutRegion, TextType, RegionType

logger = logging.getLogger(__name__)


def classify_text_regions(
    regions: List[LayoutRegion],
    page_image: Optional[object] = None,
    *,
    use_vision: bool = False,
) -> List[LayoutRegion]:
    """
    Classify each layout region as printed, handwritten, or mixed.

    Parameters
    ----------
    regions : list of LayoutRegion
        Regions to classify (from layout detection).
    page_image : PIL.Image, optional
        Page image for vision-based classification.
    use_vision : bool
        If True, use LLM vision API for classification.

    Returns
    -------
    list of LayoutRegion
        Same regions with updated ``text_type`` field.
    """
    if not regions:
        return regions

    # If vision-based layout detection already tagged handwritten regions,
    # trust those labels
    if any(r.text_type == TextType.HANDWRITTEN for r in regions):
        return regions

    if use_vision and page_image is not None:
        return _classify_via_vision(regions, page_image)

    return _classify_heuristic(regions)


def _classify_heuristic(regions: List[LayoutRegion]) -> List[LayoutRegion]:
    """
    Heuristic handwriting detection based on text characteristics.

    Handwritten text in OCR output tends to have:
    - Lower confidence scores
    - More character substitution patterns
    - Less consistent spacing
    - More non-standard character sequences
    """
    for region in regions:
        # Signatures are always handwritten
        if region.region_type == RegionType.SIGNATURE:
            region.text_type = TextType.HANDWRITTEN
            continue

        # Already classified
        if region.text_type != TextType.UNKNOWN and region.text_type != TextType.PRINTED:
            continue

        # Check for handwriting indicators in the text
        score = _handwriting_score(region.text)

        if score > 0.6:
            region.text_type = TextType.HANDWRITTEN
            region.confidence *= 0.85  # Lower confidence for handwritten
        elif score > 0.3:
            region.text_type = TextType.MIXED
            region.confidence *= 0.9
        else:
            region.text_type = TextType.PRINTED

    return regions


def _handwriting_score(text: str) -> float:
    """
    Score how likely text is handwritten based on OCR artifact patterns.

    Returns 0.0 (definitely printed) to 1.0 (definitely handwritten).
    """
    if not text or len(text) < 5:
        return 0.0

    indicators = 0
    total_checks = 6

    # 1. High ratio of non-alphanumeric characters (OCR noise)
    if text:
        non_alnum = sum(1 for c in text if not c.isalnum() and c not in " .,;:!?-/()")
        ratio = non_alnum / len(text)
        if ratio > 0.15:
            indicators += 1

    # 2. Irregular spacing (mix of single and multiple spaces)
    import re
    multi_spaces = len(re.findall(r"  +", text))
    words = len(text.split())
    if words > 0 and multi_spaces / max(words, 1) > 0.2:
        indicators += 1

    # 3. Short disconnected fragments (common in handwriting OCR)
    fragments = [w for w in text.split() if len(w) <= 2]
    if len(fragments) / max(words, 1) > 0.3:
        indicators += 1

    # 4. Mixed case within words (OCR confusion on handwriting)
    mixed_case_words = sum(
        1 for w in text.split()
        if len(w) > 2 and any(c.isupper() for c in w[1:]) and any(c.islower() for c in w)
    )
    if mixed_case_words / max(words, 1) > 0.15:
        indicators += 1

    # 5. Unusual character combinations unlikely in medical printed text
    unusual = len(re.findall(r"[|}{~`^]", text))
    if unusual > 2:
        indicators += 1

    # 6. Very few recognizable medical terms (handwriting harder to parse)
    medical_terms = len(re.findall(
        r"\b(?:mg|ml|tablet|capsule|daily|bid|tid|qid|prn|blood|test|"
        r"patient|diagnosis|medication|allergy|lab|vital|history)\b",
        text, re.IGNORECASE,
    ))
    if words > 10 and medical_terms / max(words, 1) < 0.02:
        indicators += 1

    return indicators / total_checks


def _classify_via_vision(
    regions: List[LayoutRegion],
    page_image: object,
) -> List[LayoutRegion]:
    """
    Use Groq vision API to classify handwritten vs printed regions.

    Sends the page image and asks the model to identify handwritten areas.
    Falls back to heuristic if API fails.
    """
    import base64
    import io
    import json

    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq not installed; falling back to heuristic classification")
        return _classify_heuristic(regions)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return _classify_heuristic(regions)

    try:
        buf = io.BytesIO()
        if hasattr(page_image, "save"):
            page_image.save(buf, format="PNG")
        else:
            return _classify_heuristic(regions)
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
                            "Look at this medical document image. "
                            "Does it contain any handwritten text? "
                            'Reply with JSON: {"has_handwriting": true/false, '
                            '"handwritten_description": "brief description of handwritten areas"}. '
                            "Return ONLY JSON."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }],
            max_tokens=500,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)

        has_handwriting = result.get("has_handwriting", False)

        if has_handwriting:
            # If the whole page has handwriting, mark likely regions
            for region in regions:
                if region.region_type in (RegionType.SIGNATURE, RegionType.HANDWRITTEN):
                    region.text_type = TextType.HANDWRITTEN
                elif region.confidence < 0.7:
                    # Low-confidence regions are likely handwritten
                    region.text_type = TextType.HANDWRITTEN
                else:
                    region.text_type = TextType.PRINTED
        else:
            for region in regions:
                if region.region_type == RegionType.SIGNATURE:
                    region.text_type = TextType.HANDWRITTEN
                else:
                    region.text_type = TextType.PRINTED

        return regions

    except Exception as e:
        logger.warning("Vision handwriting detection failed: %s", e)
        return _classify_heuristic(regions)
