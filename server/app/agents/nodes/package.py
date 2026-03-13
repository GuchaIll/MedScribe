import json
from pathlib import Path
from typing import Any, Dict, List

from ..state import GraphState
from .export import write_report_pdf


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles non-serializable types gracefully."""
    def default(self, o: Any) -> Any:
        if isinstance(o, type):
            return o.__name__
        try:
            return super().default(o)
        except TypeError:
            return str(o)


LIST_MERGE_KEYS = {
    "diagnoses": "code",
    "medications": "name",
    "allergies": "substance",
    "problems": "name",
    "labs": "test",
    "procedures": "name",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and not value:
        return True
    if isinstance(value, dict) and not value:
        return True
    return False


def _merge_lists(primary: List[Dict[str, Any]], fallback: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()

    for item in primary:
        merge_value = item.get(key)
        if merge_value:
            seen.add(merge_value)
        merged.append(item)

    for item in fallback:
        merge_value = item.get(key)
        if merge_value and merge_value in seen:
            continue
        merged.append(item)
        if merge_value:
            seen.add(merge_value)

    return merged


def _merge_records(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(fallback)

    for key, value in primary.items():
        if isinstance(value, dict):
            merged[key] = _merge_records(value, merged.get(key, {})) if isinstance(merged.get(key), dict) else value
            continue
        if isinstance(value, list):
            fallback_list = merged.get(key, [])
            if key in LIST_MERGE_KEYS and isinstance(fallback_list, list):
                merged[key] = _merge_lists(value, fallback_list, LIST_MERGE_KEYS[key])
            elif not _is_missing(value):
                merged[key] = value
            continue
        if not _is_missing(value):
            merged[key] = value

    return merged


def _build_report_text(state: GraphState, merged_record: Dict[str, Any]) -> str:
    summary = state.get("session_summary")
    summary_text = summary if isinstance(summary, str) else json.dumps(summary or {}, indent=2, sort_keys=True)
    clinical_note = state.get("clinical_note") or ""

    report_sections = [
        "CLINICAL DOCUMENTATION REPORT",
        f"Session ID: {state.get('session_id')}",
        f"Patient ID: {state.get('patient_id')}",
        f"Doctor ID: {state.get('doctor_id')}",
        "",
        "SESSION SUMMARY",
        summary_text,
        "",
        "CLINICAL NOTE",
        clinical_note,
        "",
        "STRUCTURED RECORD",
        json.dumps(merged_record, indent=2, sort_keys=True, cls=_SafeEncoder),
        "",
        "VALIDATION REPORT",
        json.dumps(state.get("validation_report") or {}, indent=2, sort_keys=True, cls=_SafeEncoder),
        "",
        "CONFLICT REPORT",
        json.dumps(state.get("conflict_report") or {}, indent=2, sort_keys=True, cls=_SafeEncoder),
    ]

    return "\n".join(report_sections)


def _load_template(template_name: str) -> str:
    template_path = Path(__file__).with_name(template_name)
    return template_path.read_text(encoding="utf-8")


def _render_html(template: str, context: Dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def package_outputs_node(state: GraphState) -> GraphState:
    """Package final artifacts for export and storage."""
    state = state.copy()
    structured = state.get("structured_record") or {}
    prior_profile = state.get("patient_record_fields") or state.get("inputs", {}).get("patient_profile", {})
    merged_record = _merge_records(structured, prior_profile)

    report_text = _build_report_text(state, merged_record)
    summary = state.get("session_summary")
    summary_text = summary if isinstance(summary, str) else json.dumps(summary or {}, indent=2, sort_keys=True)
    html_template = _load_template("report_template.html")
    css_styles = _load_template("report_styles.css")
    html_report = _render_html(
        html_template,
        {
            "title": "Clinical Documentation Report",
            "styles": css_styles,
            "session_id": str(state.get("session_id", "")),
            "patient_id": str(state.get("patient_id", "")),
            "doctor_id": str(state.get("doctor_id", "")),
            "session_summary": summary_text,
            "clinical_note": state.get("clinical_note") or "",
            "structured_record": json.dumps(merged_record, indent=2, sort_keys=True, cls=_SafeEncoder),
            "validation_report": json.dumps(state.get("validation_report") or {}, indent=2, sort_keys=True, cls=_SafeEncoder),
            "conflict_report": json.dumps(state.get("conflict_report") or {}, indent=2, sort_keys=True, cls=_SafeEncoder),
        },
    )

    repo_root = Path(__file__).resolve().parents[3]
    output_dir = repo_root / "storage" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    session_id = state.get("session_id", "session")
    report_path = output_dir / f"{session_id}_report.txt"
    html_path = output_dir / f"{session_id}_report.html"
    pdf_path = output_dir / f"{session_id}_report.pdf"

    # Write text report
    report_path.write_text(report_text, encoding="utf-8")
    html_path.write_text(html_report, encoding="utf-8")
    try:
        write_report_pdf(
            output_path=pdf_path,
            title="Clinical Documentation Report",
            meta=[
                ("Session ID", str(state.get("session_id", ""))),
                ("Patient ID", str(state.get("patient_id", ""))),
                ("Doctor ID", str(state.get("doctor_id", ""))),
            ],
            summary_text=summary_text,
            clinical_note=state.get("clinical_note") or "",
            structured_record=merged_record,
            validation_report=state.get("validation_report") or {},
            conflict_report=state.get("conflict_report") or {},
        )
    except RuntimeError:
        # reportlab not installed — skip PDF, continue with text + HTML
        pdf_path = None

    state.setdefault("controls", {"attempts": {}, "budget": {}, "trace_log": []})
    state["controls"]["trace_log"].append(
        {
            "node": "package_outputs",
            "report_path": str(report_path),
            "html_path": str(html_path),
            "pdf_path": str(pdf_path),
        }
    )
    state["message"] = f"Packaged outputs: {report_path.name}, {html_path.name}" + (f", {pdf_path.name}" if pdf_path else "")
    state["structured_record"] = merged_record
    return state
