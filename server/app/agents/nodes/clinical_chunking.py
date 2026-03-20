"""
Clinical-aware text chunking for medical transcription.

Extends the base recursive_text_splitter with clinical section awareness:
  - Detects SOAP headers (Subjective, Objective, Assessment, Plan)
  - Detects clinical section headings (MEDICATIONS, ALLERGIES, HISTORY, etc.)
  - Preserves section context in chunk metadata
  - Uses section boundaries as primary split points before falling back
    to sentence/character splitting

This produces higher-quality chunks for RAG retrieval because each chunk
is cohesive within a single clinical section rather than splitting across
sections where context would be lost.

Usage:
    from app.agents.nodes.clinical_chunking import clinical_text_splitter
    chunks = clinical_text_splitter(text, chunk_size=500, overlap=50)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── Clinical section patterns ───────────────────────────────────────────────

# SOAP sections (case-insensitive)
_SOAP_PATTERN = re.compile(
    r"^[ \t]*"
    r"(SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN|"
    r"S\b|O\b|A\b|P\b)"        # common abbreviations
    r"[ \t]*[:\-]",
    re.IGNORECASE | re.MULTILINE,
)

# Clinical section headings commonly found in medical notes
_SECTION_HEADINGS = [
    "CHIEF COMPLAINT",
    "HISTORY OF PRESENT ILLNESS",
    "HPI",
    "PAST MEDICAL HISTORY",
    "PMH",
    "PAST SURGICAL HISTORY",
    "PSH",
    "MEDICATIONS",
    "CURRENT MEDICATIONS",
    "ALLERGIES",
    "FAMILY HISTORY",
    "SOCIAL HISTORY",
    "REVIEW OF SYSTEMS",
    "ROS",
    "PHYSICAL EXAMINATION",
    "PHYSICAL EXAM",
    "PE",
    "VITAL SIGNS",
    "VITALS",
    "LABORATORY",
    "LABS",
    "LAB RESULTS",
    "IMAGING",
    "RADIOLOGY",
    "DIAGNOSES",
    "DIAGNOSIS",
    "DIFFERENTIAL DIAGNOSIS",
    "PROBLEMS",
    "PROBLEM LIST",
    "IMPRESSION",
    "DISPOSITION",
    "DISCHARGE INSTRUCTIONS",
    "FOLLOW UP",
    "FOLLOW-UP",
    "PROCEDURES",
    "SURGICAL NOTES",
    "OPERATIVE NOTE",
    "ANESTHESIA",
    "RECOMMENDATIONS",
    "CONSULTATION",
    "PROGRESS NOTE",
    "ADDENDUM",
]

# Build a single pattern that matches any heading at the start of a line
_HEADING_PATTERN = re.compile(
    r"^[ \t]*("
    + "|".join(re.escape(h) for h in _SECTION_HEADINGS)
    + r")[ \t]*[:\-]?",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class ClinicalChunk:
    """A text chunk with clinical section context."""
    text: str
    section: Optional[str] = None
    chunk_index: int = 0
    total_section_chunks: int = 1


@dataclass
class _Section:
    """Internal representation of a detected clinical section."""
    heading: str
    start: int          # character offset in source text
    end: int            # character offset (exclusive)
    text: str


# ── Section detection ───────────────────────────────────────────────────────

def detect_sections(text: str) -> List[_Section]:
    """
    Detect clinical section boundaries in a text.

    Returns a list of _Section objects ordered by position.
    If no clinical headings are found, returns a single section
    covering the entire text with heading="UNKNOWN".
    """
    # Collect all heading matches
    matches: List[Tuple[int, str]] = []

    for m in _SOAP_PATTERN.finditer(text):
        matches.append((m.start(), _normalize_soap(m.group(1).strip())))

    for m in _HEADING_PATTERN.finditer(text):
        heading = m.group(1).strip().upper()
        # Avoid duplicates if SOAP pattern already captured at same position
        if not any(pos == m.start() for pos, _ in matches):
            matches.append((m.start(), heading))

    # Sort by position
    matches.sort(key=lambda x: x[0])

    if not matches:
        return [_Section(heading="UNKNOWN", start=0, end=len(text), text=text)]

    sections: List[_Section] = []

    # If text before first heading, add as PREAMBLE
    if matches[0][0] > 0:
        preamble_text = text[: matches[0][0]].strip()
        if preamble_text:
            sections.append(
                _Section(
                    heading="PREAMBLE",
                    start=0,
                    end=matches[0][0],
                    text=preamble_text,
                )
            )

    # Build sections from consecutive headings
    for i, (pos, heading) in enumerate(matches):
        if i + 1 < len(matches):
            end = matches[i + 1][0]
        else:
            end = len(text)
        section_text = text[pos:end].strip()
        if section_text:
            sections.append(
                _Section(heading=heading, start=pos, end=end, text=section_text)
            )

    return sections


def _normalize_soap(label: str) -> str:
    """Normalize SOAP abbreviations to full names."""
    mapping = {
        "S": "SUBJECTIVE",
        "O": "OBJECTIVE",
        "A": "ASSESSMENT",
        "P": "PLAN",
    }
    return mapping.get(label.upper(), label.upper())


# ── Clinical-aware splitter ─────────────────────────────────────────────────

def _sub_split(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Split text within a section using sentence-boundary-aware splitting.

    This is the same algorithm as recursive_text_splitter in segment.py,
    inlined here to avoid circular dependencies.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            remainder = text[start:].strip()
            if remainder:
                chunks.append(remainder)
            break

        split_point = None
        for sep in separators:
            search_end = min(end, len(text))
            last_sep = text[start:search_end].rfind(sep)
            if last_sep != -1 and last_sep > chunk_size // 2:
                split_point = start + last_sep + len(sep)
                break

        if split_point is None:
            split_point = end

        chunk_text = text[start:split_point].strip()
        if chunk_text:
            chunks.append(chunk_text)

        start = split_point - overlap

    return chunks


def clinical_text_splitter(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[ClinicalChunk]:
    """
    Split text into chunks using clinical section awareness.

    Algorithm:
      1. Detect clinical section boundaries (SOAP, headings).
      2. For each section, if the section fits within chunk_size,
         emit it as a single chunk.
      3. Otherwise, sub-split the section using sentence-boundary
         splitting (same logic as segment.py).
      4. Tag each chunk with its section heading for downstream
         metadata enrichment.

    Args:
        text: Input text (transcript or document).
        chunk_size: Maximum chunk size in characters.
        overlap: Character overlap between chunks within the same section.

    Returns:
        List of ClinicalChunk objects with section context.
    """
    if not text or not text.strip():
        return []

    sections = detect_sections(text)
    result: List[ClinicalChunk] = []

    for section in sections:
        sub_chunks = _sub_split(section.text, chunk_size, overlap)
        total = len(sub_chunks)
        for i, chunk_text in enumerate(sub_chunks):
            result.append(
                ClinicalChunk(
                    text=chunk_text,
                    section=section.heading,
                    chunk_index=i,
                    total_section_chunks=total,
                )
            )

    return result


def clinical_chunk_conversation_log(
    conversation_log: list,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[dict]:
    """
    Chunk a conversation log using clinical-aware splitting.

    Concatenates all conversation turns into a single text block,
    applies clinical section detection, then produces ChunkArtifact-compatible
    dicts with section metadata.

    Args:
        conversation_log: List of ConversationTurn dicts.
        chunk_size: Maximum chunk size in characters.
        overlap: Character overlap between chunks.

    Returns:
        List of ChunkArtifact-compatible dicts.
    """
    import uuid

    lines: List[str] = []
    for turn in conversation_log:
        for segment in turn.get("segments", []):
            text = segment.get("cleaned_text") or segment.get("raw_text", "")
            speaker = segment.get("speaker", "Unknown")
            if text.strip():
                lines.append(f"{speaker}: {text.strip()}")

    full_text = "\n".join(lines)
    if not full_text.strip():
        return []

    clinical_chunks = clinical_text_splitter(full_text, chunk_size, overlap)

    result = []
    for chunk in clinical_chunks:
        result.append(
            {
                "chunk_id": f"chunk_{uuid.uuid4().hex[:12]}",
                "source": "transcript",
                "source_id": f"clinical_section_{chunk.section or 'unknown'}",
                "text": chunk.text,
                "start": None,
                "end": None,
                "metadata": {
                    "clinical_section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "total_section_chunks": chunk.total_section_chunks,
                    "chunking_strategy": "clinical_aware",
                },
            }
        )

    return result
