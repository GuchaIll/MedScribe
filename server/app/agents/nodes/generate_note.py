"""
Agent H â€” Note Generator (Grounded, HTML output)

Produces an HTML clinical note grounded strictly in structured_record.

Rendering conventions
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  â€¢ Known/confident fields   â†’ plain black text
  â€¢ Low-confidence (<70%)    â†’ <mark class="uncertain"> amber highlight
  â€¢ Conflicting values       â†’ <mark class="conflict">  yellow highlight
                               with tooltip showing db vs extracted value
  â€¢ Not documented           â†’ <span class="missing">Not documented</span>
                               (italic grey)
"""

import html
import json
import re
from typing import Any, Dict, List, Optional
from ..config import AgentContext
from ..state import GraphState
from ...models.llm import LLMClient

_LOW_CONF = 0.70  # Below this → amber highlight


# ── Public node ───────────────────────────────────────────────────────────────

def generate_note_node(state: GraphState, ctx: AgentContext) -> GraphState:
    state = state.copy() if isinstance(state, dict) else state

    record = state.get("structured_record", {})
    validation = state.get("validation_report", {})
    conflicts_report = state.get("conflict_report", {})

    # Support both old (record["patient"]) and new (record["demographics"]) shapes
    demo = record.get("demographics") or {}
    patient_name = (demo.get("full_name") or
                    (record.get("patient") or {}).get("name") or "")

    if not record or not patient_name:
        state["clinical_note"] = _build_html_note(record, validation, conflicts_report, {})
        return state

    controls = state.get("controls", {"attempts": {}, "budget": {}})
    budget = controls.get("budget", {})
    max_llm_calls = budget.get("max_total_llm_calls", ctx.max_llm_calls if ctx else 30)
    llm_calls_used = budget.get("llm_calls_used", 0)

    if llm_calls_used >= max_llm_calls:
        state["clinical_note"] = _build_html_note(record, validation, conflicts_report, {})
        print("[Generate Note] Budget exhausted — using template HTML note")
        return state

    # LLM generates natural-language text per section; HTML wrapping is done here
    try:
        llm = LLMClient()
        llm_calls_used += 1
        history_context = _build_history_context(state)
        sections = _call_llm_for_sections(llm, record, history_context)
        budget["llm_calls_used"] = llm_calls_used
        controls["budget"] = budget
        state["controls"] = controls
    except Exception as e:
        print(f"[Generate Note] LLM error: {e}")
        sections = {}

    state["clinical_note"] = _build_html_note(record, validation, conflicts_report, sections)
    controls["attempts"]["generate_note"] = (
        controls.get("attempts", {}).get("generate_note", 0) + 1
    )
    print(f"[Generate Note] HTML note generated ({len(state['clinical_note'])} chars)")
    return state


# ── LLM section generator ─────────────────────────────────────────────────────

def _call_llm_for_sections(llm: LLMClient, record: Dict, history_context: str) -> Dict[str, str]:
    """Ask LLM to write a short prose paragraph for each H&P section."""
    record_json = json.dumps(
        {k: v for k, v in record.items() if not k.startswith("_")},
        indent=2, default=str,
    )
    prompt = f"""You are a medical scribe. Write brief prose for each section of a clinical note.
Return ONLY a JSON object with these keys (values are 1-3 sentence strings):
  demographics, chief_complaint, hpi, past_medical_history, medications, allergies,
  family_history, social_history, review_of_systems, vitals, physical_exam, labs,
  problem_list, risk_factors, assessment, plan, diagnostic_summary

Rules:
- Use ONLY information already in the structured record below.
- If a section has no data, return null for that key.
- Do NOT add facts not present in the record.
- Do NOT use markdown -- plain text only.
- For diagnostic_summary: summarize top differential diagnoses, recommended workup,
  and key risk flags from the diagnostic_reasoning section (if present). Return null
  if no diagnostic_reasoning data exists.
{f"PATIENT HISTORY: {history_context}" if history_context else ""}

Structured Record:
{record_json}

JSON output:"""

    response = llm.generate_response(prompt).strip()
    if response.startswith("```"):
        response = re.sub(r'^```(?:json)?\s*\n?', '', response)
        response = re.sub(r'\n?```\s*$', '', response)
    try:
        result = json.loads(response)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# ── HTML builder ──────────────────────────────────────────────────────────────

_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 13px; color: #111; margin: 24px; }
  h1   { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 4px; }
  h2   { font-size: 13px; font-weight: bold; margin: 14px 0 4px; color: #222;
         border-left: 3px solid #555; padding-left: 6px; }
  table { border-collapse: collapse; width: 100%; margin: 4px 0; }
  td, th { border: 1px solid #ccc; padding: 3px 8px; font-size: 12px; }
  th { background: #f0f0f0; font-weight: bold; text-align: left; }
  ul  { margin: 2px 0 6px 18px; padding: 0; }
  li  { margin: 1px 0; }
  .missing    { color: #999; font-style: italic; }
  .uncertain  { background: #fff3cd; border-radius: 2px; padding: 0 2px; }
  .conflict   { background: #ffe066; border-radius: 2px; padding: 0 2px;
                cursor: help; border-bottom: 2px dashed #c00; }
  .warn-box   { background: #fff3cd; border: 1px solid #f0ad4e; padding: 8px 12px;
                border-radius: 4px; margin: 12px 0; font-size: 12px; }
  .warn-box ul{ margin: 4px 0 0 16px; }
  .section    { margin-bottom: 10px; }
  .label      { color: #555; font-weight: bold; min-width: 160px; display: inline-block; }
  .prose      { color: #333; margin: 2px 0 6px 0; }
  @media print { body { margin: 8px; } }
</style>
</head>
<body>
"""

_HTML_FOOT = "\n</body></html>"


def _build_html_note(record: Dict, validation: Dict, conflict_report: Dict,
                     llm_sections: Dict) -> str:
    """Assemble the full HTML note from the structured record."""
    lines: List[str] = [_HTML_HEAD]

    demo    = record.get("demographics") or {}
    patient = record.get("patient") or {}  # legacy compat

    name = demo.get("full_name") or patient.get("name") or ""
    dob  = demo.get("date_of_birth") or patient.get("dob") or ""
    sex  = demo.get("sex") or patient.get("sex") or ""
    mrn  = demo.get("mrn") or patient.get("mrn") or ""

    # Collect all conflict + low-confidence metadata from record
    rec_conflicts: List[Dict]       = record.get("_conflicts", [])
    rec_low_conf:  List[Dict]       = record.get("_low_confidence", [])
    conflict_fields = {c["field"] for c in rec_conflicts}
    low_conf_fields = {c["field"] for c in rec_low_conf}
    conf_map:  Dict[str, float]     = {c["field"]: c.get("confidence", 0.5) for c in rec_low_conf}
    db_val_map:Dict[str, str]        = {c["field"]: str(c.get("db_value", "")) for c in rec_conflicts}
    ex_val_map:Dict[str, str]        = {c["field"]: str(c.get("extracted_value", "")) for c in rec_conflicts}

    def _v(field_path: str, text: str) -> str:
        """Wrap a value text with appropriate highlight if needed."""
        if not text or text == "Not documented":
            return '<span class="missing">Not documented</span>'
        text_e = html.escape(str(text))
        if field_path in conflict_fields:
            db_e  = html.escape(db_val_map.get(field_path, "?"))
            ex_e  = html.escape(ex_val_map.get(field_path, "?"))
            tip   = f"DB: {db_e} | Extracted: {ex_e}"
            return f'<mark class="conflict" title="{tip}">{text_e}</mark>'
        if field_path in low_conf_fields:
            c = conf_map.get(field_path, 0.5)
            tip = f"Confidence: {c:.0%}"
            return f'<mark class="uncertain" title="{tip}">{text_e}</mark>'
        return text_e

    def _prose(llm_key: str) -> str:
        text = (llm_sections or {}).get(llm_key)
        if text:
            return f'<p class="prose">{html.escape(str(text))}</p>'
        return ""

    def _nd() -> str:
        return '<span class="missing">Not documented</span>'

    # ── Title ─────────────────────────────────────────────────────────────
    lines.append(f"<h1>Clinical Note — {html.escape(name) if name else _nd()}</h1>")

    # ── Warnings banner ────────────────────────────────────────────────────
    warn_items: List[str] = []
    if rec_conflicts:
        warn_items.append(f"{len(rec_conflicts)} field(s) have conflicting DB vs extracted values (highlighted in <b style='color:#c00'>yellow/dashed</b>).")
    if rec_low_conf:
        warn_items.append(f"{len(rec_low_conf)} field(s) have low extraction confidence (highlighted in <b>amber</b>).")
    schema_errs = (validation or {}).get("schema_errors", [])
    if schema_errs:
        warn_items.append(f"Schema errors: {html.escape(', '.join(str(e) for e in schema_errs[:3]))}.")
    if (conflict_report or {}).get("conflicts"):
        warn_items.append(f"{len(conflict_report['conflicts'])} unresolved field conflict(s) require review.")
    if warn_items:
        items_html = "".join(f"<li>{w}</li>" for w in warn_items)
        lines.append(f'<div class="warn-box"><b>⚠ Review Required</b><ul>{items_html}</ul></div>')

    # ── Demographics ──────────────────────────────────────────────────────
    lines.append('<div class="section">')
    lines.append("<h2>Demographics</h2>")
    ci  = demo.get("contact_info") or {}
    ins = demo.get("insurance") or {}
    ec  = demo.get("emergency_contact") or {}
    rows = [
        ("Full Name",         _v("demographics.full_name",     name)),
        ("Date of Birth",     _v("demographics.date_of_birth", dob)),
        ("Sex",               _v("demographics.sex",           sex)),
        ("MRN",               _v("demographics.mrn",           mrn)),
        ("Phone",             _v("demographics.contact_info.phone",   ci.get("phone") or "")),
        ("Email",             _v("demographics.contact_info.email",   ci.get("email") or "")),
        ("Address",           _v("demographics.contact_info.address", ci.get("address") or "")),
        ("Insurance",         _v("demographics.insurance.provider",   ins.get("provider") or "")),
        ("Insurance #",       _v("demographics.insurance.policy_number", ins.get("policy_number") or "")),
        ("Emergency Contact", _v("demographics.emergency_contact.name",
                                  (ec.get("name") or "") +
                                  (f" ({ec['relationship']})" if ec.get("relationship") else "") +
                                  (f" — {ec['phone']}" if ec.get("phone") else ""))),
    ]
    lines.append("<table><tr><th>Field</th><th>Value</th></tr>")
    for label, val in rows:
        lines.append(f"<tr><td><b>{label}</b></td><td>{val}</td></tr>")
    lines.append("</table>")
    lines.append("</div>")

    # ── Allergies (safety — top of note) ──────────────────────────────────
    lines.append('<div class="section">')
    lines.append("<h2>🚨 Allergies</h2>")
    allergies = record.get("allergies", [])
    if allergies:
        lines.append("<ul>")
        for a in allergies:
            substance = html.escape(str(a.get("substance", "Unknown")))
            reaction  = a.get("reaction", "")
            severity  = a.get("severity", "")
            cat       = a.get("category", "")
            conf      = a.get("confidence", 1.0)
            detail    = " — ".join(filter(None, [reaction, severity, cat]))
            tag       = f"{substance}{': ' + html.escape(detail) if detail else ''}"
            if conf < _LOW_CONF:
                tag = f'<mark class="uncertain" title="Confidence: {conf:.0%}">{tag}</mark>'
            lines.append(f"<li>{tag}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append("</div>")

    # ── Chief Complaint ────────────────────────────────────────────────────
    cc = record.get("chief_complaint") or {}
    lines.append('<div class="section"><h2>Chief Complaint</h2>')
    cc_text = cc.get("free_text") or ""
    if cc_text:
        parts = [_v("chief_complaint.free_text", cc_text)]
        if cc.get("onset"):    parts.append(f"Onset: {html.escape(cc['onset'])}")
        if cc.get("duration"): parts.append(f"Duration: {html.escape(cc['duration'])}")
        if cc.get("severity"): parts.append(f"Severity: {html.escape(cc['severity'])}")
        if cc.get("location"): parts.append(f"Location: {html.escape(cc['location'])}")
        lines.append("<p>" + " | ".join(parts) + "</p>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("chief_complaint"))
    lines.append("</div>")

    # ── History of Present Illness ────────────────────────────────────────
    hpi = record.get("hpi", [])
    lines.append('<div class="section"><h2>History of Present Illness (HPI)</h2>')
    if hpi:
        lines.append('<table><tr><th>Symptom</th><th>Onset</th><th>Progression</th>'
                     '<th>Triggers</th><th>Relieving</th><th>Associated</th></tr>')
        for ev in hpi:
            conf = ev.get("confidence", 1.0)
            def _hcell(txt: str) -> str:
                t = html.escape(str(txt)) if txt else '<span class="missing">—</span>'
                if conf < _LOW_CONF:
                    return f'<mark class="uncertain" title="Confidence: {conf:.0%}">{t}</mark>'
                return t
            lines.append(
                f"<tr><td>{_hcell(ev.get('symptom',''))}</td>"
                f"<td>{_hcell(ev.get('onset',''))}</td>"
                f"<td>{_hcell(ev.get('progression',''))}</td>"
                f"<td>{_hcell(ev.get('triggers',''))}</td>"
                f"<td>{_hcell(ev.get('relieving_factors',''))}</td>"
                f"<td>{_hcell(ev.get('associated_symptoms',''))}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("hpi"))
    lines.append("</div>")

    # ── Past Medical History ──────────────────────────────────────────────
    pmh = record.get("past_medical_history") or {}
    chronic = pmh.get("chronic_conditions", [])
    surgeries = pmh.get("surgeries", [])
    hosps = pmh.get("hospitalizations", [])
    lines.append('<div class="section"><h2>Past Medical History</h2>')
    if chronic:
        lines.append("<b>Chronic Conditions:</b><ul>")
        for c in chronic:
            name_c = html.escape(str(c.get("name", "Unknown")))
            code   = c.get("icd10_code", "")
            status = c.get("status", "")
            onset  = c.get("onset_year", "")
            src    = c.get("source", "")
            conf_c = c.get("confidence", 1.0)
            detail = " | ".join(filter(None, [
                f"[{code}]" if code else None,
                status, onset,
                f'<i style="color:#888">({src})</i>' if src == "prior_record" else None,
            ]))
            item = f"{name_c}{': ' + detail if detail else ''}"
            if conf_c < _LOW_CONF:
                item = f'<mark class="uncertain" title="Confidence: {conf_c:.0%}">{item}</mark>'
            lines.append(f"<li>{item}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>Chronic conditions: {_nd()}</p>")
    if surgeries:
        lines.append("<b>Surgeries:</b><ul>")
        for s in surgeries:
            n = html.escape(str(s.get("name", "?")))
            d = f" ({html.escape(s['date'])})" if s.get("date") else ""
            lines.append(f"<li>{n}{d}</li>")
        lines.append("</ul>")
    if hosps:
        lines.append("<b>Hospitalizations:</b><ul>")
        for h in hosps:
            r = html.escape(str(h.get("reason", "?")))
            d = f" ({html.escape(h['date'])})" if h.get("date") else ""
            lines.append(f"<li>{r}{d}</li>")
        lines.append("</ul>")
    lines.append(_prose("past_medical_history"))
    lines.append("</div>")

    # ── Medications ────────────────────────────────────────────────────────
    meds = record.get("medications", [])
    lines.append('<div class="section"><h2>Medications</h2>')
    if meds:
        lines.append('<table><tr><th>Drug</th><th>Dose</th><th>Route</th>'
                     '<th>Frequency</th><th>Indication</th><th>Start</th></tr>')
        for m in meds:
            conf_m = m.get("confidence", 1.0)
            def _mc(txt: str) -> str:
                t = html.escape(str(txt)) if txt else '<span class="missing">—</span>'
                if conf_m < _LOW_CONF:
                    return f'<mark class="uncertain" title="Confidence: {conf_m:.0%}">{t}</mark>'
                return t
            src_tag = ' <i style="color:#888">(prior)</i>' if m.get("source") == "prior_record" else ""
            lines.append(
                f"<tr><td>{_mc(m.get('name',''))}{src_tag}</td>"
                f"<td>{_mc(m.get('dose',''))}</td>"
                f"<td>{_mc(m.get('route',''))}</td>"
                f"<td>{_mc(m.get('frequency',''))}</td>"
                f"<td>{_mc(m.get('indication',''))}</td>"
                f"<td>{_mc(m.get('start_date',''))}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("medications"))
    lines.append("</div>")

    # ── Family History ────────────────────────────────────────────────────
    fh = record.get("family_history", [])
    lines.append('<div class="section"><h2>Family History</h2>')
    if fh:
        lines.append("<ul>")
        for f in fh:
            member = html.escape(str(f.get("member", "Unknown")))
            conds  = ", ".join(html.escape(c) for c in f.get("conditions", []))
            alive  = f.get("alive")
            cod    = f.get("cause_of_death", "")
            alive_str = "" if alive is None else (" (alive)" if alive else " (deceased)")
            cod_str = f" — died: {html.escape(cod)}" if cod else ""
            detail = f": {conds}" if conds else ""
            lines.append(f"<li><b>{member}</b>{alive_str}{detail}{cod_str}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("family_history"))
    lines.append("</div>")

    # ── Social History ────────────────────────────────────────────────────
    sh = record.get("social_history") or {}
    lines.append('<div class="section"><h2>Social History</h2>')
    sh_rows = [
        ("Tobacco",    sh.get("tobacco")),
        ("Alcohol",    sh.get("alcohol")),
        ("Drug Use",   sh.get("drug_use")),
        ("Occupation", sh.get("occupation")),
        ("Exercise",   sh.get("exercise")),
        ("Diet",       sh.get("diet")),
    ]
    any_sh = any(v for _, v in sh_rows)
    if any_sh:
        lines.append("<table>")
        for label, val in sh_rows:
            v_html = html.escape(str(val)) if val else '<span class="missing">Not documented</span>'
            lines.append(f"<tr><td><b>{label}</b></td><td>{v_html}</td></tr>")
        lines.append("</table>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("social_history"))
    lines.append("</div>")

    # ── Review of Systems ─────────────────────────────────────────────────
    ros = record.get("review_of_systems") or {}
    ros_populated = {k: v for k, v in ros.items() if v and k != "confidence"}
    lines.append('<div class="section"><h2>Review of Systems</h2>')
    if ros_populated:
        lines.append("<ul>")
        for system, finding in ros_populated.items():
            lines.append(f"<li><b>{html.escape(system.replace('_', ' ').title())}:</b> {html.escape(str(finding))}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("review_of_systems"))
    lines.append("</div>")

    # ── Vitals ─────────────────────────────────────────────────────────────
    vitals = record.get("vitals") or {}
    # support both old list shape and new dict shape
    if isinstance(vitals, list):
        vitals_dict: Dict[str, str] = {v.get("type", f"vital_{i}"): v.get("value", "") for i, v in enumerate(vitals)}
    else:
        vitals_dict = {k: v for k, v in vitals.items() if v and k not in ("timestamp", "confidence")}
    lines.append('<div class="section"><h2>Vitals</h2>')
    if vitals_dict:
        label_map = {
            "blood_pressure": "Blood Pressure", "heart_rate": "Heart Rate",
            "respiratory_rate": "Respiratory Rate", "temperature": "Temperature",
            "spo2": "O₂ Saturation", "height": "Height", "weight": "Weight", "bmi": "BMI",
        }
        lines.append("<table><tr><th>Measurement</th><th>Value</th></tr>")
        for k, v in vitals_dict.items():
            label = label_map.get(k, k.replace("_", " ").title())
            fp    = f"vitals.{k}"
            lines.append(f"<tr><td>{label}</td><td>{_v(fp, str(v))}</td></tr>")
        lines.append("</table>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("vitals"))
    lines.append("</div>")

    # ── Physical Exam ─────────────────────────────────────────────────────
    pe = record.get("physical_exam") or {}
    pe_data = {k: v for k, v in pe.items() if v and k != "confidence"}
    lines.append('<div class="section"><h2>Physical Examination</h2>')
    if pe_data:
        lines.append("<ul>")
        for system, finding in pe_data.items():
            lines.append(f"<li><b>{html.escape(system.replace('_', ' ').title())}:</b> {html.escape(str(finding))}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("physical_exam"))
    lines.append("</div>")

    # ── Labs ───────────────────────────────────────────────────────────────
    labs = record.get("labs", [])
    lines.append('<div class="section"><h2>Laboratory Results</h2>')
    if labs:
        lines.append('<table><tr><th>Test</th><th>Value</th><th>Unit</th>'
                     '<th>Reference</th><th>Date</th><th>Abnormal</th></tr>')
        for lab in labs:
            conf_l = lab.get("confidence", 1.0)
            abnormal = lab.get("abnormal")
            val_html = html.escape(str(lab.get("value", "")))
            if abnormal:
                val_html = f'<b style="color:#c00">{val_html}</b>'
            if conf_l < _LOW_CONF:
                val_html = f'<mark class="uncertain" title="Confidence: {conf_l:.0%}">{val_html}</mark>'
            lines.append(
                f"<tr><td>{html.escape(str(lab.get('test','')))}</td>"
                f"<td>{val_html}</td>"
                f"<td>{html.escape(str(lab.get('unit','')))}</td>"
                f"<td>{html.escape(str(lab.get('reference_range','')))}</td>"
                f"<td>{html.escape(str(lab.get('date','')))}</td>"
                f"<td>{'⚠' if abnormal else ''}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("labs"))
    lines.append("</div>")

    # ── Problem List ──────────────────────────────────────────────────────
    probs = record.get("problem_list", [])
    lines.append('<div class="section"><h2>Problem List</h2>')
    if probs:
        lines.append("<ul>")
        for p in probs:
            n    = html.escape(str(p.get("name", "?")))
            st   = p.get("status", "")
            conf_p = p.get("confidence", 1.0)
            src  = p.get("source", "")
            tag  = f"{n}{': ' + html.escape(st) if st else ''}"
            if src == "prior_record":
                tag += ' <i style="color:#888">(prior)</i>'
            if conf_p < _LOW_CONF:
                tag = f'<mark class="uncertain" title="Confidence: {conf_p:.0%}">{tag}</mark>'
            lines.append(f"<li>{tag}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("problem_list"))
    lines.append("</div>")

    # ── Risk Factors ──────────────────────────────────────────────────────
    rfs = record.get("risk_factors", [])
    lines.append('<div class="section"><h2>Risk Factors</h2>')
    if rfs:
        lines.append("<ul>")
        for rf in rfs:
            n   = html.escape(str(rf.get("name", "?")))
            sev = rf.get("severity", "")
            conf_r = rf.get("confidence", 1.0)
            tag = f"{n}{': ' + html.escape(sev) if sev else ''}"
            if conf_r < _LOW_CONF:
                tag = f'<mark class="uncertain" title="Confidence: {conf_r:.0%}">{tag}</mark>'
            lines.append(f"<li>{tag}</li>")
        lines.append("</ul>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append("</div>")

    # ── Assessment ────────────────────────────────────────────────────────
    assess = record.get("assessment") or {}
    lines.append('<div class="section"><h2>Assessment</h2>')
    likely = assess.get("likely_diagnoses", [])
    diff   = assess.get("differential_diagnoses", [])
    reas   = assess.get("clinical_reasoning", "")
    if likely:
        lines.append("<b>Likely Diagnoses:</b><ul>")
        for dx in likely:
            lines.append(f"<li>{html.escape(str(dx))}</li>")
        lines.append("</ul>")
    if diff:
        lines.append("<b>Differential Diagnoses:</b><ul>")
        for dx in diff:
            lines.append(f"<li>{html.escape(str(dx))}</li>")
        lines.append("</ul>")
    if reas:
        lines.append(f"<p>{html.escape(reas)}</p>")
    # Legacy diagnoses list
    for dx in record.get("diagnoses", []):
        code = dx.get("code", "")
        desc = dx.get("description", "")
        conf_d = dx.get("confidence", 1.0)
        text_d = f"[{html.escape(code)}] " if code else ""
        text_d += html.escape(str(desc))
        if conf_d < _LOW_CONF:
            text_d = f'<mark class="uncertain" title="Confidence: {conf_d:.0%}">{text_d}</mark>'
        lines.append(f"<p>• {text_d}</p>")
    if not likely and not diff and not reas and not record.get("diagnoses"):
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("assessment"))
    lines.append("</div>")

    # ── Diagnostic Intelligence ───────────────────────────────────────────
    dx_reasoning = record.get("diagnostic_reasoning") or {}
    dx_html = _build_diagnostic_intelligence_section(dx_reasoning)
    if dx_html:
        lines.append(dx_html)

    # ── Plan ───────────────────────────────────────────────────────────────
    plan = record.get("plan") or {}
    lines.append('<div class="section"><h2>Plan</h2>')
    plan_meds  = plan.get("medications_prescribed", [])
    plan_tests = plan.get("tests_ordered", [])
    plan_life  = plan.get("lifestyle_recommendations", [])
    plan_fu    = plan.get("follow_up", "")
    plan_refs  = plan.get("referrals", [])
    any_plan = any([plan_meds, plan_tests, plan_life, plan_fu, plan_refs])
    if any_plan:
        if plan_meds:
            lines.append("<b>Medications Prescribed:</b><ul>")
            for m in plan_meds:
                lines.append(f"<li>{html.escape(str(m))}</li>")
            lines.append("</ul>")
        if plan_tests:
            lines.append("<b>Tests Ordered:</b><ul>")
            for t in plan_tests:
                lines.append(f"<li>{html.escape(str(t))}</li>")
            lines.append("</ul>")
        if plan_life:
            lines.append("<b>Lifestyle Recommendations:</b><ul>")
            for l in plan_life:
                lines.append(f"<li>{html.escape(str(l))}</li>")
            lines.append("</ul>")
        if plan_refs:
            lines.append("<b>Referrals:</b><ul>")
            for r in plan_refs:
                lines.append(f"<li>{html.escape(str(r))}</li>")
            lines.append("</ul>")
        if plan_fu:
            lines.append(f"<p><b>Follow-up:</b> {html.escape(str(plan_fu))}</p>")
    else:
        lines.append(f"<p>{_nd()}</p>")
    lines.append(_prose("plan"))
    lines.append("</div>")

    lines.append('<p style="color:#999;font-size:11px;margin-top:20px;border-top:1px solid #ddd;padding-top:6px">'
                 'Generated from structured clinical record. '
                 'Values in <mark class="conflict">yellow/dashed</mark> indicate DB vs extraction conflicts. '
                 'Values in <mark class="uncertain">amber</mark> have confidence &lt;70%.'
                 '</p>')
    lines.append(_HTML_FOOT)
    return "\n".join(lines)


# ── Diagnostic Intelligence section builder ───────────────────────────────────

def _build_diagnostic_intelligence_section(dx_reasoning: Dict) -> str:
    """
    Build the Diagnostic Intelligence HTML section from diagnostic reasoning data.

    Args:
        dx_reasoning: dict with top_diagnoses, recommended_tests, risk_flags,
                      treatment_guidance, reasoning_trace, method.

    Returns:
        HTML string for the section, or empty string if no data.
    """
    top_dx = dx_reasoning.get("top_diagnoses", [])
    rec_tests = dx_reasoning.get("recommended_tests", [])
    risk_flags_dx = dx_reasoning.get("risk_flags", [])
    tx_guidance = dx_reasoning.get("treatment_guidance", [])
    reasoning_trace = dx_reasoning.get("reasoning_trace", "")
    dx_method = dx_reasoning.get("method", "")

    has_dx_intel = any([top_dx, rec_tests, risk_flags_dx, tx_guidance])
    if not has_dx_intel:
        return ""

    lines: list[str] = []
    lines.append('<div class="section"><h2>Diagnostic Intelligence</h2>')
    if dx_method:
        lines.append(f'<p style="color:#888;font-size:11px">[Analysis method: {html.escape(dx_method)}]</p>')

    # Differential diagnoses with confidence and reasoning
    if top_dx:
        lines.append("<b>Differential Diagnoses (ranked by likelihood):</b>")
        lines.append('<table><tr><th>#</th><th>Diagnosis</th><th>ICD-10</th>'
                     '<th>Confidence</th><th>Reasoning</th></tr>')
        for idx, dx in enumerate(top_dx, 1):
            dx_name = html.escape(str(dx.get("name", "?")))
            icd = html.escape(str(dx.get("icd10", ""))) if dx.get("icd10") else '<span class="missing">--</span>'
            conf = dx.get("confidence")
            conf_str = f"{conf:.0%}" if conf is not None else '<span class="missing">--</span>'
            if conf is not None and conf < _LOW_CONF:
                conf_str = f'<mark class="uncertain">{conf_str}</mark>'
            reason = html.escape(str(dx.get("reasoning", ""))) if dx.get("reasoning") else ""
            lines.append(f"<tr><td>{idx}</td><td><b>{dx_name}</b></td>"
                         f"<td>{icd}</td><td>{conf_str}</td><td>{reason}</td></tr>")
        lines.append("</table>")

        # Supporting/against evidence (compact)
        for dx in top_dx:
            support = dx.get("supporting_evidence", [])
            against = dx.get("against_evidence", [])
            if support or against:
                dx_name = html.escape(str(dx.get("name", "?")))
                lines.append(f'<p style="margin:2px 0 0 8px;font-size:11px"><i>{dx_name}:</i>')
                if support:
                    lines.append(f' <span style="color:#070">Supporting: {html.escape(", ".join(str(s) for s in support))}</span>')
                if against:
                    lines.append(f' <span style="color:#c00">Against: {html.escape(", ".join(str(a) for a in against))}</span>')
                lines.append("</p>")

    # Recommended tests/workup
    if rec_tests:
        lines.append("<b>Recommended Workup:</b>")
        lines.append('<table><tr><th>Test</th><th>Priority</th>'
                     '<th>Rationale</th><th>Expected Finding</th></tr>')
        for t in rec_tests:
            test_name = html.escape(str(t.get("test", "?")))
            priority = html.escape(str(t.get("priority", "routine")))
            priority_style = ""
            if priority == "stat":
                priority_style = ' style="color:#c00;font-weight:bold"'
            elif priority == "urgent":
                priority_style = ' style="color:#b60"'
            rationale = html.escape(str(t.get("rationale", ""))) if t.get("rationale") else ""
            expected = html.escape(str(t.get("expected_finding", ""))) if t.get("expected_finding") else ""
            lines.append(f"<tr><td>{test_name}</td>"
                         f"<td{priority_style}>{priority}</td>"
                         f"<td>{rationale}</td><td>{expected}</td></tr>")
        lines.append("</table>")

    # Clinical risk flags
    if risk_flags_dx:
        lines.append("<b>Clinical Risk Flags:</b><ul>")
        for rf in risk_flags_dx:
            flag_text = html.escape(str(rf.get("flag", "?")))
            severity = rf.get("severity", "moderate")
            action = rf.get("action", "")
            sev_style = ""
            if severity == "critical":
                sev_style = ' style="color:#c00;font-weight:bold"'
            elif severity == "high":
                sev_style = ' style="color:#b60"'
            action_str = f" -- {html.escape(action)}" if action else ""
            lines.append(f'<li{sev_style}>[{html.escape(severity).upper()}] {flag_text}{action_str}</li>')
        lines.append("</ul>")

    # Treatment guidance
    if tx_guidance:
        lines.append("<b>Treatment Guidance:</b><ul>")
        for tg in tx_guidance:
            cond = html.escape(str(tg.get("condition", "?")))
            rec = html.escape(str(tg.get("recommendation", "")))
            ev_level = tg.get("evidence_level", "")
            precautions = tg.get("precautions", [])
            ev_tag = f' <span style="color:#888">[{html.escape(ev_level)}]</span>' if ev_level else ""
            lines.append(f"<li><b>{cond}:</b> {rec}{ev_tag}")
            if precautions:
                prec_str = ", ".join(html.escape(str(p)) for p in precautions)
                lines.append(f'<br><span style="color:#b60;font-size:11px">Precautions: {prec_str}</span>')
            lines.append("</li>")
        lines.append("</ul>")

    # Reasoning trace (collapsible)
    if reasoning_trace:
        lines.append("<details><summary style='cursor:pointer;color:#555;font-size:12px'>"
                     "Show diagnostic reasoning trace</summary>")
        lines.append(f'<p style="font-size:11px;color:#555;margin:4px 0 0 12px">'
                     f'{html.escape(str(reasoning_trace))}</p>')
        lines.append("</details>")

    lines.append("</div>")
    return "\n".join(lines)


# ── History context helper ────────────────────────────────────────────────────

def _build_history_context(state: GraphState) -> str:
    prf = state.get("patient_record_fields") or {}
    if not prf.get("loaded_from_db"):
        return ""
    parts = []
    visit_count = prf.get("visit_count", 0)
    if visit_count > 0:
        parts.append(f"Visit #{visit_count + 1}.")
    demographics = prf.get("demographics", {})
    if demographics.get("full_name"):
        parts.append(f"Patient: {demographics['full_name']}.")
    prior_facts = prf.get("prior_facts", {})
    for fact_type, facts in prior_facts.items():
        if facts:
            keys = [f.get("fact_key", "?") for f in facts[:4]]
            parts.append(f"Prior {fact_type}s: {', '.join(keys)}.")
    return " ".join(parts)

