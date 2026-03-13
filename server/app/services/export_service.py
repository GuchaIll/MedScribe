"""
Export Service — single source of truth for document generation.

Consolidates:
  - app/agents/nodes/export.py  (reportlab-based PDF)
  - app/utils/pdf_generator.py  (hand-crafted raw PDF)
  - app/core/record_generator.py (Jinja2 HTML + optional WeasyPrint)

into one service with a clean API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.core.record_generator import RecordGenerator


class ExportService:
    """
    Unified document export for medical records.

    Supports HTML, PDF, and plain text output via the
    RecordGenerator / Jinja2 pipeline.
    """

    def __init__(self, generator: RecordGenerator | None = None):
        self._generator = generator

    @property
    def generator(self) -> RecordGenerator:
        if self._generator is None:
            self._generator = RecordGenerator()
        return self._generator

    def to_html(
        self,
        record: Dict[str, Any],
        template: str = "soap",
        suggestions: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render record to HTML string."""
        return self.generator.generate(record, template, suggestions)

    def to_pdf(
        self,
        record: Dict[str, Any],
        template: str = "soap",
        suggestions: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Render record to PDF bytes."""
        return self.generator.generate_pdf(record, template, suggestions)

    def to_text(
        self,
        record: Dict[str, Any],
        template: str = "soap",
    ) -> str:
        """Render record to plain text."""
        return self.generator.generate_text(record, template)

    def save(
        self,
        record: Dict[str, Any],
        template: str,
        output_path: Path | str,
        fmt: str = "html",
        suggestions: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Generate and save to disk."""
        output_path = Path(output_path)
        self.generator.save_to_file(
            record, template, str(output_path), fmt, suggestions
        )
        return output_path
