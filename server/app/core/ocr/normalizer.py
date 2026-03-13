"""
Post-OCR text normalisation for medical documents.

Cleans up common OCR artefacts and expands medical abbreviations so
downstream NLP pipeline nodes receive cleaner input.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common medical abbreviation mappings
# ---------------------------------------------------------------------------
# Keys are case-insensitive regex patterns; values are expansions.
# Patterns are compiled once at module load for performance.

_ABBREVIATION_MAP: Dict[str, str] = {
    r"\bpt\b": "patient",
    r"\bpts\b": "patients",
    r"\bhx\b": "history",
    r"\bdx\b": "diagnosis",
    r"\brx\b": "prescription",
    r"\btx\b": "treatment",
    r"\bsx\b": "symptoms",
    r"\bfx\b": "fracture",
    r"\bhtn\b": "hypertension",
    r"\bdm\b": "diabetes mellitus",
    r"\bchf\b": "congestive heart failure",
    r"\bcopd\b": "chronic obstructive pulmonary disease",
    r"\bmi\b": "myocardial infarction",
    r"\bcva\b": "cerebrovascular accident",
    r"\bdvt\b": "deep vein thrombosis",
    r"\bpe\b": "pulmonary embolism",
    r"\buti\b": "urinary tract infection",
    r"\buo\b": "urine output",
    r"\bbid\b": "twice daily",
    r"\btid\b": "three times daily",
    r"\bqid\b": "four times daily",
    r"\bprn\b": "as needed",
    r"\bpo\b": "by mouth",
    r"\biv\b": "intravenous",
    r"\bim\b": "intramuscular",
    r"\bsc\b": "subcutaneous",
    r"\bbp\b": "blood pressure",
    r"\bhr\b": "heart rate",
    r"\brr\b": "respiratory rate",
    r"\bwbc\b": "white blood cell",
    r"\brbc\b": "red blood cell",
    r"\bhgb\b": "hemoglobin",
    r"\bhct\b": "hematocrit",
    r"\bbun\b": "blood urea nitrogen",
    r"\bcbc\b": "complete blood count",
    r"\bcmp\b": "comprehensive metabolic panel",
    r"\bekg\b": "electrocardiogram",
    r"\becg\b": "electrocardiogram",
    r"\bnpo\b": "nothing by mouth",
}

_COMPILED_ABBREVIATIONS = [
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in _ABBREVIATION_MAP.items()
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_ocr_text(
    text: str,
    *,
    fix_whitespace: bool = True,
    fix_line_breaks: bool = True,
    expand_abbreviations: bool = True,
    fix_common_ocr_errors: bool = True,
) -> str:
    """
    Apply a battery of normalisations to raw OCR output.

    Parameters
    ----------
    text:
        Raw text from the OCR extractor.
    fix_whitespace:
        Collapse multiple spaces / tabs into single spaces.
    fix_line_breaks:
        Merge lines that were split mid-sentence by the scanner.
    expand_abbreviations:
        Replace common medical abbreviations with full terms.
    fix_common_ocr_errors:
        Correct frequent mis-reads (e.g. ``rn`` → ``m``, ``cl`` → ``d``).

    Returns
    -------
    str
        Cleaned text.
    """
    if not text:
        return text

    if fix_common_ocr_errors:
        text = _fix_ocr_errors(text)

    if fix_whitespace:
        text = _fix_whitespace(text)

    if fix_line_breaks:
        text = _fix_line_breaks(text)

    if expand_abbreviations:
        text = _expand_abbreviations(text)

    return text.strip()


def get_abbreviation_map() -> Dict[str, str]:
    """Return a copy of the medical abbreviation mapping."""
    return dict(_ABBREVIATION_MAP)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fix_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    text = re.sub(r"[ \t]+", " ", text)
    # Remove spaces before punctuation
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text


def _fix_line_breaks(text: str) -> str:
    """
    Merge lines that appear to be continuation of the same sentence
    (no terminal punctuation or section header pattern).
    """
    lines = text.split("\n")
    merged: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            merged.append("")  # keep paragraph breaks
            continue

        if merged and merged[-1] and not _is_sentence_end(merged[-1]):
            # Previous line didn't end a sentence → merge
            merged[-1] = merged[-1].rstrip() + " " + stripped
        else:
            merged.append(stripped)

    return "\n".join(merged)


def _is_sentence_end(line: str) -> bool:
    """Check whether *line* ends with terminal punctuation or is a header."""
    line = line.rstrip()
    if not line:
        return True
    # Ends with sentence-ending punctuation
    if line[-1] in ".!?:":
        return True
    # Likely a section header (ALL CAPS or short enough)
    if line.isupper() and len(line) < 60:
        return True
    return False


def _expand_abbreviations(text: str) -> str:
    """Replace known medical abbreviations."""
    for pattern, replacement in _COMPILED_ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    return text


def _fix_ocr_errors(text: str) -> str:
    """
    Fix very common OCR misreads.

    These are conservative — only applied when the wrong character sequence
    is unlikely to be intentional text.
    """
    # 'l' (lowercase L) misread as '1' in certain words
    text = re.sub(r"\b(\w+)1(\w+)\b", _maybe_fix_digit_in_word, text)

    # '0' misread as 'O' at start of numbers
    text = re.sub(r"\bO(\d{2,})\b", r"0\1", text)

    # Double-spaces that are OCR artefacts (already handled by whitespace fixer,
    # but cleaning here avoids order-dependency)
    text = re.sub(r"  +", " ", text)

    return text


def _maybe_fix_digit_in_word(match: re.Match) -> str:
    """Replace '1' with 'l' when surrounded by letters (likely OCR misread)."""
    before, after = match.group(1), match.group(2)
    if before.isalpha() and after.isalpha():
        return f"{before}l{after}"
    return match.group(0)
