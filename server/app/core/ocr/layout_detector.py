"""
Document layout detection for medical documents.

Two-tier approach:
  - Tier 1 (default): Heuristic analysis using pdfplumber metadata
    (font sizes, positions, table detection, whitespace analysis)
  - Tier 2 (optional): LLM vision-based layout detection via Groq API

Identifies: headers, paragraphs, tables, key-value pairs, lists,
handwritten regions, signatures, checkboxes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RegionType(str, Enum):
    """Layout region classifications."""
    HEADER = "header"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    KEY_VALUE = "key_value"
    LIST = "list"
    SIGNATURE = "signature"
    CHECKBOX = "checkbox"
    HANDWRITTEN = "handwritten"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"


class TextType(str, Enum):
    """Text rendering type."""
    PRINTED = "printed"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class LayoutRegion:
    """A detected layout region on a page."""
    region_type: RegionType
    text: str = ""
    text_type: TextType = TextType.PRINTED
    confidence: float = 0.8
    bounding_box: Optional[Tuple[float, float, float, float]] = None  # x0, y0, x1, y1
    metadata: Dict[str, Any] = field(default_factory=dict)


def detect_layout(
    text: str,
    *,
    tables: Optional[List[List[List[str]]]] = None,
    page_image: Optional[object] = None,
    use_vision: bool = False,
) -> List[LayoutRegion]:
    """
    Detect layout structure in a page of text.

    Parameters
    ----------
    text : str
        Raw extracted text from OCR or text layer.
    tables : list, optional
        Pre-extracted tables from pdfplumber.
    page_image : PIL.Image, optional
        Page image for vision-based detection.
    use_vision : bool
        If True, use LLM vision API for layout detection (Tier 2).

    Returns
    -------
    List[LayoutRegion]
        Detected layout regions ordered by position.
    """
    if use_vision and page_image is not None:
        vision_regions = _detect_layout_vision(page_image)
        if vision_regions:
            return vision_regions

    return _detect_layout_heuristic(text, tables=tables)


def _detect_layout_heuristic(
    text: str,
    *,
    tables: Optional[List[List[List[str]]]] = None,
) -> List[LayoutRegion]:
    """
    Tier 1: Heuristic layout detection from text content.

    Uses patterns to identify headers, key-value pairs, tables, lists, etc.
    """
    if not text:
        return []

    regions: List[LayoutRegion] = []
    lines = text.split("\n")

    # ── Add pre-extracted tables as regions ──────────────────────────────
    if tables:
        for table in tables:
            table_text = _format_table(table)
            regions.append(LayoutRegion(
                region_type=RegionType.TABLE,
                text=table_text,
                confidence=0.9,
                metadata={"rows": len(table), "cols": len(table[0]) if table else 0},
            ))

    # ── Process lines ───────────────────────────────────────────────────
    current_paragraph: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines (paragraph boundary)
        if not line:
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []
            i += 1
            continue

        # Check for header patterns
        if _is_header(line):
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []
            regions.append(LayoutRegion(
                region_type=RegionType.HEADER,
                text=line,
                confidence=0.85,
            ))
            i += 1
            continue

        # Check for key-value pair  (e.g., "Name: John Smith" or "DOB   01/15/1970")
        kv = _extract_key_value(line)
        if kv:
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []
            regions.append(LayoutRegion(
                region_type=RegionType.KEY_VALUE,
                text=line,
                confidence=0.8,
                metadata={"key": kv[0], "value": kv[1]},
            ))
            i += 1
            continue

        # Check for list items
        if _is_list_item(line):
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []

            # Collect consecutive list items
            list_items = [line]
            while i + 1 < len(lines) and _is_list_item(lines[i + 1].strip()):
                i += 1
                list_items.append(lines[i].strip())
            regions.append(LayoutRegion(
                region_type=RegionType.LIST,
                text="\n".join(list_items),
                confidence=0.8,
                metadata={"items": len(list_items)},
            ))
            i += 1
            continue

        # Check for checkbox patterns
        if _is_checkbox(line):
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []
            checked = _is_checkbox_checked(line)
            regions.append(LayoutRegion(
                region_type=RegionType.CHECKBOX,
                text=line,
                confidence=0.75,
                metadata={"checked": checked},
            ))
            i += 1
            continue

        # Check for page number
        if _is_page_number(line):
            i += 1
            continue  # Skip page numbers

        # Check for signature line
        if _is_signature_line(line):
            if current_paragraph:
                regions.append(_make_paragraph_region(current_paragraph))
                current_paragraph = []
            regions.append(LayoutRegion(
                region_type=RegionType.SIGNATURE,
                text=line,
                confidence=0.7,
            ))
            i += 1
            continue

        # Default: accumulate as paragraph text
        current_paragraph.append(line)
        i += 1

    # Flush remaining paragraph
    if current_paragraph:
        regions.append(_make_paragraph_region(current_paragraph))

    return regions


def _detect_layout_vision(page_image: object) -> List[LayoutRegion]:
    """
    Tier 2: LLM vision-based layout detection.

    Sends the page image to Groq's vision API to identify layout regions.
    Falls back to heuristic if the API is unavailable or errors.
    """
    import os
    import base64
    import io
    import json

    try:
        from groq import Groq
        from PIL import Image
    except ImportError:
        logger.warning("groq or Pillow not installed; falling back to heuristic layout")
        return []

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY not set; falling back to heuristic layout")
        return []

    try:
        # Convert image to base64
        buf = io.BytesIO()
        if hasattr(page_image, "save"):
            page_image.save(buf, format="PNG")
        else:
            return []
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
                            "Analyze this medical document image. Identify all layout regions. "
                            "For each region, output a JSON array of objects with keys: "
                            '"type" (one of: header, paragraph, table, key_value, list, '
                            'handwritten, signature, checkbox), '
                            '"text" (the text content), '
                            '"confidence" (0.0-1.0). '
                            "Return ONLY the JSON array, no other text."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }],
            max_tokens=4000,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        # Extract JSON from response (may be wrapped in markdown code blocks)
        if "```" in raw:
            json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
            if json_match:
                raw = json_match.group(1)

        items = json.loads(raw)
        regions = []
        for item in items:
            region_type = _parse_region_type(item.get("type", "unknown"))
            regions.append(LayoutRegion(
                region_type=region_type,
                text=item.get("text", ""),
                text_type=TextType.HANDWRITTEN if region_type == RegionType.HANDWRITTEN else TextType.PRINTED,
                confidence=float(item.get("confidence", 0.7)),
            ))
        return regions

    except Exception as e:
        logger.warning("Vision layout detection failed: %s", e)
        return []


# ── Pattern matchers ────────────────────────────────────────────────────────

def _is_header(line: str) -> bool:
    """Detect section headers in medical documents."""
    if not line:
        return False
    # ALL CAPS short lines (common section headers)
    if line.isupper() and 3 < len(line) < 80:
        return True
    # Ends with colon and is relatively short (field header)
    if line.endswith(":") and len(line) < 50 and " " not in line.rstrip(":"):
        return True
    # Common medical section headers
    header_patterns = [
        r"^(?:CHIEF\s+COMPLAINT|HISTORY\s+OF\s+PRESENT\s+ILLNESS|HPI)",
        r"^(?:PAST\s+MEDICAL\s+HISTORY|PMH|PAST\s+SURGICAL\s+HISTORY|PSH)",
        r"^(?:MEDICATIONS?|CURRENT\s+MEDICATIONS?|ALLERGIES|KNOWN\s+ALLERGIES)",
        r"^(?:SOCIAL\s+HISTORY|FAMILY\s+HISTORY|REVIEW\s+OF\s+SYSTEMS|ROS)",
        r"^(?:PHYSICAL\s+EXAM(?:INATION)?|VITALS?|VITAL\s+SIGNS)",
        r"^(?:ASSESSMENT|PLAN|ASSESSMENT\s+(?:AND|&)\s+PLAN|A/P)",
        r"^(?:LAB(?:ORATORY)?\s+RESULTS?|IMAGING|DIAGNOSTIC\s+STUDIES)",
        r"^(?:DISCHARGE\s+(?:SUMMARY|INSTRUCTIONS|DIAGNOSIS))",
        r"^(?:SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN)$",  # SOAP
        r"^(?:ADMISSION\s+(?:DATE|DIAGNOSIS)|DISCHARGE\s+DATE)",
        r"^(?:PROCEDURES?|OPERATIONS?|ORDERS?|FOLLOW[\s-]?UP)",
    ]
    for pattern in header_patterns:
        if re.match(pattern, line, re.IGNORECASE):
            return True
    return False


def _extract_key_value(line: str) -> Optional[Tuple[str, str]]:
    """Extract key:value pairs from a line."""
    # Pattern: "Key: Value" or "Key  Value" (with significant whitespace gap)
    match = re.match(r"^([A-Za-z][A-Za-z\s/]{1,40}):\s+(.+)$", line)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Pattern: "Key    Value" (tab or multiple spaces separating)
    match = re.match(r"^([A-Za-z][A-Za-z\s/]{1,30})\s{3,}(.+)$", line)
    if match:
        key_candidate = match.group(1).strip()
        # Must look like a field name (short, capitalized, no sentences)
        if len(key_candidate.split()) <= 4 and not key_candidate.endswith("."):
            return key_candidate, match.group(2).strip()

    return None


def _is_list_item(line: str) -> bool:
    """Check if a line looks like a list item."""
    return bool(re.match(r"^\s*(?:[-•●○◆▪]\s+|\d+[.)]\s+|[a-zA-Z][.)]\s+)", line))


def _is_checkbox(line: str) -> bool:
    """Check if a line contains checkbox-like patterns."""
    return bool(re.match(r"^\s*(?:\[[ xX✓✗]\]|☐|☑|☒|□|■)", line))


def _is_checkbox_checked(line: str) -> bool:
    """Check if a checkbox is checked."""
    return bool(re.match(r"^\s*(?:\[[xX✓]\]|☑|☒|■)", line))


def _is_page_number(line: str) -> bool:
    """Check if line is just a page number."""
    return bool(re.match(r"^\s*(?:Page\s+)?\d{1,4}\s*(?:of\s+\d{1,4})?\s*$", line, re.IGNORECASE))


def _is_signature_line(line: str) -> bool:
    """Check if line looks like a signature block."""
    if re.match(r"^_{5,}$", line):
        return True
    if re.match(r"^(?:Signature|Signed|Physician|Provider|MD|DO|NP|PA)[\s:_]", line, re.IGNORECASE):
        return True
    return False


def _make_paragraph_region(lines: List[str]) -> LayoutRegion:
    """Create a paragraph region from accumulated lines."""
    return LayoutRegion(
        region_type=RegionType.PARAGRAPH,
        text=" ".join(lines),
        confidence=0.85,
    )


def _format_table(table: List[List[str]]) -> str:
    """Format a pdfplumber table as readable text."""
    rows = []
    for row in table:
        cells = [str(cell or "").strip() for cell in row]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _parse_region_type(type_str: str) -> RegionType:
    """Parse a region type string into the enum."""
    type_map = {
        "header": RegionType.HEADER,
        "paragraph": RegionType.PARAGRAPH,
        "table": RegionType.TABLE,
        "key_value": RegionType.KEY_VALUE,
        "list": RegionType.LIST,
        "signature": RegionType.SIGNATURE,
        "checkbox": RegionType.CHECKBOX,
        "handwritten": RegionType.HANDWRITTEN,
    }
    return type_map.get(type_str.lower(), RegionType.UNKNOWN)
