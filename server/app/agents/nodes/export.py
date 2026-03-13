from pathlib import Path
from typing import Any, Dict, List, Tuple


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if key == "confidence":
                continue
            parts.append(f"{key}: {val}")
        return ", ".join(parts) if parts else "N/A"
    if isinstance(value, list):
        return "; ".join(_format_value(item) for item in value) or "N/A"
    return str(value)


def _build_structured_rows(record: Dict[str, Any]) -> List[List[str]]:
    rows: List[List[str]] = [["Section", "Field", "Value"]]

    def add_section(title: str) -> None:
        rows.append([title, "", ""])

    def add_field(section: str, field: str, value: Any) -> None:
        rows.append([section, field, _format_value(value)])

    patient = record.get("patient", {})
    visit = record.get("visit", {})
    diagnoses = record.get("diagnoses", [])
    medications = record.get("medications", [])
    allergies = record.get("allergies", [])

    add_section("Patient Demographics")
    for key in ("name", "dob", "age", "sex", "mrn"):
        if key in patient:
            add_field("Patient", key.replace("_", " ").title(), patient.get(key))

    add_section("Visit Details")
    for key in ("date", "type", "location", "provider"):
        if key in visit:
            add_field("Visit", key.replace("_", " ").title(), visit.get(key))

    add_section("Diagnoses")
    if diagnoses:
        for item in diagnoses:
            code = item.get("code") if isinstance(item, dict) else item
            add_field("Diagnoses", "Code", code)
            if isinstance(item, dict) and item.get("description"):
                add_field("Diagnoses", "Description", item.get("description"))
    else:
        add_field("Diagnoses", "Code", "N/A")

    add_section("Medications")
    if medications:
        for item in medications:
            add_field("Medications", "Name", item.get("name") if isinstance(item, dict) else item)
            if isinstance(item, dict):
                for key in ("dose", "route", "frequency"):
                    if item.get(key):
                        add_field("Medications", key.title(), item.get(key))
    else:
        add_field("Medications", "Name", "N/A")

    add_section("Allergies")
    if allergies:
        for item in allergies:
            add_field("Allergies", "Substance", item.get("substance") if isinstance(item, dict) else item)
            if isinstance(item, dict) and item.get("reaction"):
                add_field("Allergies", "Reaction", item.get("reaction"))
    else:
        add_field("Allergies", "Substance", "N/A")

    return rows


def write_report_pdf(
    output_path: Path,
    title: str,
    meta: List[Tuple[str, str]],
    summary_text: str,
    clinical_note: str,
    structured_record: Dict[str, Any],
    validation_report: Dict[str, Any],
    conflict_report: Dict[str, Any],
) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is not available. Install reportlab to enable PDF export."
        ) from exc

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        textColor=colors.white,
        backColor=colors.HexColor("#577aa6"),
        alignment=1,
        padding=6,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#2f3a4a"),
        spaceBefore=12,
        spaceAfter=6,
    )
    pre_style = ParagraphStyle(
        "Preformatted",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=8.5,
        leading=10.5,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    story: List[Any] = [Paragraph(title, title_style), Spacer(1, 0.2 * inch)]

    if meta:
        meta_table = Table([[k, v] for k, v in meta], colWidths=[1.5 * inch, 4.8 * inch])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#c7d2e0")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1f2937")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.extend([meta_table, Spacer(1, 0.2 * inch)])

    story.append(Paragraph("Session Summary", section_style))
    story.append(Preformatted(summary_text or "N/A", pre_style))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Clinical Note", section_style))
    story.append(Preformatted(clinical_note or "N/A", pre_style))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Structured Record", section_style))
    rows = _build_structured_rows(structured_record)
    table = Table(rows, colWidths=[1.6 * inch, 1.6 * inch, 3.2 * inch])
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#577aa6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )
    for idx in range(1, len(rows)):
        if rows[idx][1] == "" and rows[idx][2] == "":
            table_style.add("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#d3dbea"))
            table_style.add("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold")
    table.setStyle(table_style)
    story.extend([table, Spacer(1, 0.15 * inch)])

    story.append(Paragraph("Validation Report", section_style))
    story.append(Preformatted(_format_value(validation_report), pre_style))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Conflict Report", section_style))
    story.append(Preformatted(_format_value(conflict_report), pre_style))

    doc.build(story)
