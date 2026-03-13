"""
Medical Record Generator with Template Support.

Generates formatted medical records from structured data using templates:
- SOAP Note
- Discharge Summary
- Consultation Note
- Progress Note

Supports both HTML and PDF output formats.
"""

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
import io


class RecordGenerator:
    """
    Generator for medical records using Jinja2 templates.

    Supports multiple output formats:
    - HTML (for viewing/printing)
    - PDF (via WeasyPrint - optional)
    - Plain text (fallback)
    """

    TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

    def __init__(self):
        """Initialize record generator with template environment."""
        # Create templates directory if it doesn't exist
        self.TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

        # Setup Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATE_DIR)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Add custom filters
        self.env.filters['format_date'] = self._format_date
        self.env.filters['format_list'] = self._format_list

    def generate(
        self,
        record: Dict[str, Any],
        template_name: str,
        clinical_suggestions: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate formatted medical record from template.

        Args:
            record: Structured medical record data
            template_name: Template to use (soap, discharge, consultation, progress)
            clinical_suggestions: Optional clinical suggestions to include

        Returns:
            Rendered HTML string
        """
        # Load template
        template = self.env.get_template(f"{template_name}.html")

        # Prepare context
        context = {
            "record": record,
            "clinical_suggestions": clinical_suggestions or {},
            "generated_at": datetime.now(),
            "generator_version": "1.0.0"
        }

        # Render template
        return template.render(**context)

    def generate_pdf(
        self,
        record: Dict[str, Any],
        template_name: str,
        clinical_suggestions: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """
        Generate PDF from template.

        Args:
            record: Structured medical record data
            template_name: Template to use
            clinical_suggestions: Optional clinical suggestions

        Returns:
            PDF bytes
        """
        # Generate HTML first
        html = self.generate(record, template_name, clinical_suggestions)

        # Convert to PDF
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html).write_pdf()
            return pdf_bytes
        except (ImportError, OSError):
            # WeasyPrint not available or native libs missing, return HTML as fallback
            return html.encode('utf-8')

    def generate_text(
        self,
        record: Dict[str, Any],
        template_name: str
    ) -> str:
        """
        Generate plain text version of medical record.

        Args:
            record: Structured medical record data
            template_name: Template to use

        Returns:
            Plain text string
        """
        # Generate HTML
        html = self.generate(record, template_name)

        # Simple HTML to text conversion (strip tags)
        import re
        text = re.sub('<[^<]+?>', '', html)
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Remove extra blank lines
        return text.strip()

    # Alias so callers can use either name
    generate_plain_text = generate_text

    def save_to_file(
        self,
        record: Dict[str, Any],
        template_name: str,
        output_path: str,
        format: str = "html",
        clinical_suggestions: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save generated record to file.

        Args:
            record: Structured medical record data
            template_name: Template to use
            output_path: Path to save file
            format: Output format (html, pdf, txt)
            clinical_suggestions: Optional clinical suggestions

        Returns:
            Path to saved file
        """
        if format == "pdf":
            content = self.generate_pdf(record, template_name, clinical_suggestions)
            mode = 'wb'
        elif format in ("txt", "text"):
            content = self.generate_text(record, template_name)
            mode = 'w'
        else:  # html
            content = self.generate(record, template_name, clinical_suggestions)
            mode = 'w'

        with open(output_path, mode) as f:
            f.write(content)

        return output_path

    def _format_date(self, value):
        """Jinja2 filter to format dates."""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return value
        return value

    def _format_list(self, items, separator=", "):
        """Jinja2 filter to format lists."""
        if isinstance(items, list):
            return separator.join(str(item) for item in items)
        return str(items)


def get_record_generator() -> RecordGenerator:
    """
    Factory function to create record generator.

    Returns:
        RecordGenerator instance
    """
    return RecordGenerator()
