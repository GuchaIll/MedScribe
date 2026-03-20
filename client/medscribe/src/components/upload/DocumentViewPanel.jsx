/**
 * DocumentViewPanel – split-pane document viewer
 *
 * Left  (42%): original document preview (PDF iframe / image / fallback)
 * Right (58%): full editable consolidated medical-record form
 *               • blue highlight  → modified / extracted field
 *               • yellow highlight → low confidence (< 70%)
 *               • red highlight    → DB vs extracted conflict (with tooltip)
 *               • "Not documented" placeholder → grey italic
 *               • 3-4 sentence auto-summary at top
 */

import { useState, useMemo, useCallback, useEffect } from "react";

// ─── Constants ────────────────────────────────────────────────────────────────
const LOW_CONF = 0.70;

const S = {
  normal:   { background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 6 },
  modified: { background: "#eff6ff", border: "1px solid #3b82f6", borderRadius: 6 },
  lowConf:  { background: "#fefce8", border: "1px solid #eab308", borderRadius: 6 },
  conflict: { background: "#fef2f2", border: "1px solid #ef4444", borderRadius: 6 },
};

const INPUT_BASE = {
  width: "100%", padding: "6px 10px", fontSize: 12, fontFamily: "'DM Sans', sans-serif",
  color: "#1a1a1a", lineHeight: 1.5, resize: "vertical", boxSizing: "border-box",
};

const TA_BASE = { ...INPUT_BASE, minHeight: 56 };

// ─── Auto-summary (3–4 sentences) ────────────────────────────────────────────
function buildSummary(rec) {
  if (!rec) return null;
  const demo = rec.demographics || {};
  const name = demo.full_name || "The patient";
  const dob  = demo.date_of_birth ? ` (DOB ${demo.date_of_birth})` : "";
  const cc   = rec.chief_complaint?.free_text;
  const meds = (rec.medications || []).length;
  const algs = (rec.allergies || []).length;
  const pmhList = (rec.past_medical_history?.chronic_conditions || [])
    .slice(0, 3).map((c) => c.name || c).filter(Boolean);
  const assessment =
    rec.assessment?.clinical_reasoning ||
    (rec.assessment?.likely_diagnoses || []).join(", ") ||
    (rec.diagnoses || []).map((d) => d.description).filter(Boolean).join(", ");
  const followUp = rec.plan?.follow_up;

  const sentences = [];
  let s1 = `${name}${dob} presents`;
  if (cc) s1 += ` with ${cc.replace(/[.!?]+$/, "")}`;
  sentences.push(s1 + ".");

  if (pmhList.length > 0) {
    sentences.push(`PMH includes ${pmhList.join(", ")}${(rec.past_medical_history?.chronic_conditions || []).length > 3 ? ", and others" : ""}.`);
  }
  if (meds > 0 || algs > 0) {
    sentences.push(
      `Currently on ${meds} medication${meds !== 1 ? "s" : ""}` +
      (algs > 0 ? ` with ${algs} documented allerg${algs !== 1 ? "ies" : "y"}` : "") + "."
    );
  }
  if (assessment) sentences.push(`Assessment: ${assessment}.`);
  else if (followUp) sentences.push(`Follow-up: ${followUp}.`);

  return sentences.slice(0, 4).join(" ");
}

// ─── Deep-clone then set value at dotted path ─────────────────────────────────
function setPath(obj, dotPath, value) {
  const copy = JSON.parse(JSON.stringify(obj));
  const parts = dotPath.split(".");
  let cur = copy;
  for (let i = 0; i < parts.length - 1; i++) {
    if (cur[parts[i]] == null) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
  return copy;
}

// ─── Update item inside a nested list ────────────────────────────────────────
function setListField(obj, dotPath, idx, field, value) {
  const copy = JSON.parse(JSON.stringify(obj));
  const parts = dotPath.split(".");
  let arr = copy;
  for (const p of parts) arr = arr[p];
  if (arr[idx] != null) arr[idx][field] = value;
  return copy;
}

// ─── Section heading ──────────────────────────────────────────────────────────
function Heading({ children }) {
  return (
    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.13em",
      textTransform: "uppercase", color: "#374151", fontFamily: "'DM Mono', monospace",
      marginTop: 22, marginBottom: 8, paddingBottom: 4,
      borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
      {children}
    </div>
  );
}

// ─── Label for a single row ───────────────────────────────────────────────────
function Label({ children }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 600, color: "#555",
      fontFamily: "'DM Mono', monospace", marginBottom: 3 }}>
      {children}
    </div>
  );
}

// ─── Editable input field ─────────────────────────────────────────────────────
function Field({ label, fieldPath, value, onChange, multiline, lowConf, conflict, conflictTip, modified, placeholder }) {
  const style = conflict ? S.conflict : lowConf ? S.lowConf : modified ? S.modified : S.normal;
  const title = conflict ? conflictTip
    : lowConf ? `Low confidence (< ${LOW_CONF * 100}%)`
    : modified ? "Populated from extracted data" : undefined;
  const inputStyle = { ...( multiline ? TA_BASE : INPUT_BASE), ...style };
  return (
    <div style={{ marginBottom: 10 }}>
      {label && <Label>{label}</Label>}
      {multiline ? (
        <textarea
          value={value ?? ""}
          placeholder={placeholder || "Not documented"}
          title={title}
          onChange={(e) => onChange(e.target.value)}
          style={inputStyle}
        />
      ) : (
        <input
          type="text"
          value={value ?? ""}
          placeholder={placeholder || "Not documented"}
          title={title}
          onChange={(e) => onChange(e.target.value)}
          style={inputStyle}
        />
      )}
    </div>
  );
}

// ─── Two-column grid for key-value dicts ──────────────────────────────────────
function KVGrid({ children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 14px" }}>
      {children}
    </div>
  );
}

// ─── Build a partial structured record from flat field_changes list ───────────
// Mirrors the backend _ocr_fields_to_structured_record helper; used as a
// client-side fallback when the backend structured_record is unavailable.
function buildRecordFromFieldChanges(fieldChanges) {
  if (!fieldChanges || fieldChanges.length === 0) return null;
  const r = JSON.parse(JSON.stringify(EMPTY_RECORD));
  for (const fc of fieldChanges) {
    const { field_name: fn, value: v } = fc;
    if (v == null || v === "") continue;
    const n = (fn || "").toLowerCase();
    // Demographics
    if (n === "patient_name" || n === "full_name") r.demographics.full_name = String(v);
    else if (n === "date_of_birth" || n === "dob") r.demographics.date_of_birth = String(v);
    else if (n === "age") r.demographics.age = String(v);
    else if (n === "sex") r.demographics.sex = String(v);
    else if (n === "gender") { r.demographics.gender = String(v); if (!r.demographics.sex) r.demographics.sex = String(v); }
    else if (n === "mrn") r.demographics.mrn = String(v);
    else if (n === "phone") r.demographics.contact_info.phone = String(v);
    else if (n === "email") r.demographics.contact_info.email = String(v);
    else if (n === "address") r.demographics.contact_info.address = String(v);
    else if (n === "insurance_provider") r.demographics.insurance.provider = String(v);
    else if (n === "insurance_policy") r.demographics.insurance.policy_number = String(v);
    // Chief complaint
    else if (n === "chief_complaint" || n === "cc") r.chief_complaint.free_text = String(v);
    else if (n === "onset") r.chief_complaint.onset = String(v);
    else if (n === "duration") r.chief_complaint.duration = String(v);
    else if (n === "severity") r.chief_complaint.severity = String(v);
    // Vitals
    else if (n === "blood_pressure" || n === "bp") r.vitals.blood_pressure = String(v);
    else if (n === "heart_rate" || n === "hr" || n === "pulse") r.vitals.heart_rate = String(v);
    else if (n === "respiratory_rate" || n === "rr") r.vitals.respiratory_rate = String(v);
    else if (n === "temperature" || n === "temp") r.vitals.temperature = String(v);
    else if (n === "spo2" || n === "oxygen_saturation") r.vitals.spo2 = String(v);
    else if (n === "height") r.vitals.height = String(v);
    else if (n === "weight") r.vitals.weight = String(v);
    else if (n === "bmi") r.vitals.bmi = String(v);
    // List fields
    else if (n === "lab_result") r.labs.push(typeof v === "object" ? v : { test: String(v), value: "", units: "" });
    else if (n === "medication") r.medications.push(typeof v === "object" ? v : { name: String(v), dose: "", frequency: "", route: "" });
    else if (n === "allergy") r.allergies.push(typeof v === "object" ? v : { allergen: String(v), reaction: "", severity: "" });
    else if (n === "chronic_condition") r.past_medical_history.chronic_conditions.push(typeof v === "object" ? v : { name: String(v) });
    else if (n === "problem" || n === "diagnosis") r.problem_list.push(typeof v === "object" ? v : { description: String(v) });
    else if (n === "risk_factor") r.risk_factors.push(typeof v === "object" ? v : { factor: String(v) });
    // Social history
    else if (n === "tobacco" || n === "smoking") r.social_history.tobacco = String(v);
    else if (n === "alcohol") r.social_history.alcohol = String(v);
    else if (n === "occupation") r.social_history.occupation = String(v);
    // Assessment / plan
    else if (n === "assessment" || n === "impression") r.assessment.clinical_reasoning = String(v);
    else if (n === "follow_up") r.plan.follow_up = String(v);
  }
  return r;
}

// ─── Main Component ───────────────────────────────────────────────────────────
const EMPTY_RECORD = {
  demographics: { full_name: "", date_of_birth: "", age: "", sex: "", gender: "", mrn: "",
    contact_info: { phone: "", email: "", address: "" },
    insurance: { provider: "", policy_number: "" },
    emergency_contact: { name: "", relationship: "", phone: "" } },
  chief_complaint: { free_text: "", onset: "", duration: "", severity: "", location: "" },
  hpi: [],
  past_medical_history: { chronic_conditions: [], surgeries: [], hospitalizations: [] },
  medications: [],
  allergies: [],
  family_history: [],
  social_history: { tobacco: "", alcohol: "", drug_use: "", occupation: "", exercise: "", diet: "" },
  review_of_systems: {},
  vitals: { blood_pressure: "", heart_rate: "", respiratory_rate: "", temperature: "", spo2: "", height: "", weight: "", bmi: "" },
  physical_exam: {},
  labs: [],
  problem_list: [],
  risk_factors: [],
  assessment: { likely_diagnoses: [], differential_diagnoses: [], clinical_reasoning: "" },
  plan: { medications_prescribed: [], tests_ordered: [], lifestyle_recommendations: [], referrals: [], follow_up: "" },
  _conflicts: [],
  _low_confidence: [],
};

export default function DocumentViewPanel({ doc, structuredRecord, onBack, onSave }) {
  const [rec, setRec] = useState(() => {
    const base = structuredRecord
      || buildRecordFromFieldChanges(doc?.fieldChanges)
      || EMPTY_RECORD;
    return JSON.parse(JSON.stringify(base));
  });
  const [changed, setChanged] = useState(false);

  // Re-sync rec when a new structuredRecord arrives from the parent
  // (e.g. OCR finishes after the panel is already open)
  // NOTE: do NOT depend on doc?.fieldChanges (array ref) — that changes every
  // render and would reset the form on every keystroke. Use a stable id instead.
  const docId = doc?.documentId || doc?.name;
  useEffect(() => {
    if (structuredRecord) {
      setRec(JSON.parse(JSON.stringify(structuredRecord)));
      setChanged(false);
    } else if (doc?.fieldChanges?.length) {
      // Fallback: build a partial record from the flat fieldChanges list
      const built = buildRecordFromFieldChanges(doc.fieldChanges);
      if (built) {
        setRec(JSON.parse(JSON.stringify(built)));
        setChanged(false);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structuredRecord, docId]);

  // ── Conflict / low-confidence lookups ──────────────────────────────────────
  const lowConfSet = useMemo(
    () => new Set((rec._low_confidence || []).map((l) => l.field)),
    [rec._low_confidence]
  );
  const conflictMap = useMemo(() => {
    const m = new Map();
    (rec._conflicts || []).forEach((c) => m.set(c.field, c));
    return m;
  }, [rec._conflicts]);

  // ── Modified / populated field detection ───────────────────────────────────
  // A field is "modified" if it was populated from extraction (non-empty and
  // differs from the empty default).  We also check _db_seeded_fields if present.
  const modifiedSet = useMemo(() => {
    const s = new Set(rec._db_seeded_fields || []);
    const walk = (obj, prefix) => {
      if (obj == null) return;
      if (typeof obj !== "object" || Array.isArray(obj)) return;
      for (const [key, val] of Object.entries(obj)) {
        if (key.startsWith("_")) continue;
        const fp = prefix ? `${prefix}.${key}` : key;
        if (typeof val === "string" && val.trim() !== "") s.add(fp);
        else if (typeof val === "number") s.add(fp);
        else if (Array.isArray(val) && val.length > 0) s.add(fp);
        else if (typeof val === "object" && val !== null) walk(val, fp);
      }
    };
    walk(structuredRecord, "");
    return s;
  }, [structuredRecord, rec._db_seeded_fields]);

  const isLow  = (fp) => lowConfSet.has(fp);
  const isCon  = (fp) => conflictMap.has(fp);
  const isMod  = (fp) => modifiedSet.has(fp);
  const conTip = (fp) => {
    const c = conflictMap.get(fp);
    return c ? `DB: ${c.db_value}  |  Extracted: ${c.extracted_value}` : undefined;
  };

  const summary = useMemo(() => buildSummary(rec), [rec]);

  // ── Update helpers ─────────────────────────────────────────────────────────
  const update = useCallback((path, val) => {
    setRec((r) => setPath(r, path, val));
    setChanged(true);
  }, []);

  const updItemField = useCallback((listPath, idx, field, val) => {
    setRec((r) => setListField(r, listPath, idx, field, val));
    setChanged(true);
  }, []);

  // List-to-textarea helpers (join/split by newline for simple lists)
  const listToText = (arr, key) =>
    (arr || []).map((i) => (typeof i === "string" ? i : i[key] || "")).join("\n");
  const textToList = (text, key) =>
    text.split("\n").map((s) => s.trim()).filter(Boolean).map((s) => ({ [key]: s }));

  // Style picker for inline fields (priority: conflict > lowConf > modified > normal)
  const pickS = (fp) => isCon(fp) ? S.conflict : isLow(fp) ? S.lowConf : isMod(fp) ? S.modified : S.normal;

  // ── Coerce value for display — objects become readable strings ───────────
  const displayVal = (raw) => {
    if (raw == null) return "";
    if (typeof raw === "string") return raw;
    if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
    // dict/array → show sub-field values joined (skip nulls)
    if (typeof raw === "object" && !Array.isArray(raw)) {
      return Object.entries(raw)
        .filter(([, v]) => v != null && v !== "" && v !== "None")
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
    }
    if (Array.isArray(raw)) return raw.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join(", ");
    return String(raw);
  };

  // ── Field helper that wires status ────────────────────────────────────────
  const F = ({ fp, label, multiline, placeholder }) => {
    const rawVal = fp.split(".").reduce((o, k) => o?.[k], rec);
    return (
      <Field
        label={label}
        fieldPath={fp}
        value={displayVal(rawVal)}
        onChange={(v) => update(fp, v)}
        multiline={multiline}
        lowConf={isLow(fp)}
        conflict={isCon(fp)}
        conflictTip={conTip(fp)}
        modified={isMod(fp)}
        placeholder={placeholder}
      />
    );
  };

  // ── Document preview (left pane) ──────────────────────────────────────────
  const previewUrl = doc?.previewUrl;
  const fileName   = doc?.name || "Document";
  const isImage    = /\.(png|jpe?g|gif|bmp|webp)$/i.test(fileName);
  const isPdf      = /\.pdf$/i.test(fileName);

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>

      {/* ── Left: document preview ─────────────────────────────────────────── */}
      <div style={{ width: "42%", flexShrink: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid rgba(0,0,0,0.08)", background: "#f8f9fa" }}>

        {/* Preview toolbar */}
        <div style={{ padding: "10px 16px", background: "#fff",
          borderBottom: "1px solid rgba(0,0,0,0.07)",
          display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <button onClick={onBack}
            style={{ background: "none", border: "none", cursor: "pointer",
              fontSize: 16, color: "#666", lineHeight: 1, padding: "2px 4px" }}
            title="Back to document list">
            ←
          </button>
          <div style={{ flex: 1, overflow: "hidden" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a1a",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {fileName}
            </div>
            <div style={{ fontSize: 10, color: "#aaa", fontFamily: "'DM Mono', monospace" }}>
              {doc?.documentType || doc?.type || ""}{doc?.date ? ` · ${doc.date}` : ""}
              {doc?.confidence != null ? ` · ${doc.confidence}% confidence` : ""}
            </div>
          </div>
          {doc?.status && (
            <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
              background: doc.status === "Processed" ? "rgba(34,197,94,0.1)" :
                          doc.status === "Conflicts" ? "rgba(239,68,68,0.1)" : "rgba(234,179,8,0.1)",
              color: doc.status === "Processed" ? "#16a34a" :
                     doc.status === "Conflicts" ? "#dc2626" : "#a16207",
              fontFamily: "'DM Mono', monospace" }}>
              {doc.status}
            </span>
          )}
        </div>

        {/* Actual preview */}
        <div style={{ flex: 1, overflow: "hidden", display: "flex",
          alignItems: previewUrl && !isPdf ? "center" : "stretch",
          justifyContent: "center", padding: previewUrl && !isPdf ? 16 : 0 }}>
          {previewUrl && isPdf ? (
            <iframe
              src={previewUrl}
              title={fileName}
              style={{ width: "100%", height: "100%", border: "none" }}
            />
          ) : previewUrl && isImage ? (
            <img
              src={previewUrl}
              alt={fileName}
              style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain",
                borderRadius: 8, boxShadow: "0 2px 16px rgba(0,0,0,0.12)" }}
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%", gap: 12, color: "#aaa" }}>
              <div style={{ width: 64, height: 64, borderRadius: 12, background: "rgba(0,0,0,0.07)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 13, fontWeight: 700, fontFamily: "'DM Mono', monospace", color: "#666" }}>
                {doc?.type || "DOC"}
              </div>
              <span style={{ fontSize: 12, color: "#bbb", fontFamily: "'DM Mono', monospace",
                textAlign: "center", maxWidth: 200, lineHeight: 1.5 }}>
                {previewUrl ? "Loading preview…" : "Preview not available.\nDocument was processed server-side."}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Right: consolidated record form ──────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column",
        background: "#ffffff", color: "#1a1a1a" }}>

        {/* Header bar */}
        <div style={{ padding: "12px 24px", borderBottom: "1px solid rgba(0,0,0,0.07)",
          background: "#fff", flexShrink: 0, display: "flex",
          alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#1a1a1a", letterSpacing: "0.04em" }}>
              Consolidated Record
            </div>
            <div style={{ fontSize: 10, color: "#aaa", fontFamily: "'DM Mono', monospace", marginTop: 1 }}>
              {modifiedSet.size > 0 && (
                <span style={{ marginRight: 10, color: "#2563eb" }}>
                  ● {modifiedSet.size} extracted field{modifiedSet.size !== 1 ? "s" : ""}
                </span>
              )}
              {lowConfSet.size > 0 && (
                <span style={{ marginRight: 10, color: "#a16207" }}>
                  ⚠ {lowConfSet.size} uncertain field{lowConfSet.size !== 1 ? "s" : ""}
                </span>
              )}
              {conflictMap.size > 0 && (
                <span style={{ color: "#dc2626" }}>
                  ✕ {conflictMap.size} conflict{conflictMap.size !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
          {changed && onSave && (
            <button
              onClick={() => { onSave(rec); setChanged(false); }}
              style={{ padding: "5px 14px", borderRadius: 99, border: "1px solid rgba(0,0,0,0.15)",
                background: "#1a1a1a", color: "#fff", fontSize: 11, fontWeight: 600,
                cursor: "pointer", fontFamily: "inherit" }}>
              Save changes
            </button>
          )}
        </div>

        <div style={{ padding: "20px 24px 40px" }}>

          {/* ── Auto-summary ──────────────────────────────────────────────── */}
          {summary && (
            <div style={{ padding: "12px 16px", borderRadius: 10,
              background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.06)",
              marginBottom: 8 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.13em",
                textTransform: "uppercase", color: "#aaa",
                fontFamily: "'DM Mono', monospace", marginBottom: 6 }}>
                Summary
              </div>
              <p style={{ fontSize: 12, lineHeight: 1.65, color: "#333",
                fontFamily: "'Lora', Georgia, serif", margin: 0 }}>
                {summary}
              </p>
            </div>
          )}

          {/* ═══════════════════════════════════════════ DEMOGRAPHICS ═══ */}
          <Heading>Demographics</Heading>
          <KVGrid>
            <F fp="demographics.full_name"     label="Full Name" />
            <F fp="demographics.date_of_birth" label="Date of Birth" placeholder="YYYY-MM-DD" />
            <F fp="demographics.age"           label="Age" placeholder="e.g. 45" />
            <F fp="demographics.gender"        label="Gender" />
            <F fp="demographics.sex"           label="Biological Sex" />
            <F fp="demographics.mrn"           label="MRN" />
          </KVGrid>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "#888", fontFamily: "'DM Mono', monospace",
            marginTop: 12, marginBottom: 6 }}>
            Anthropometrics
          </div>
          <KVGrid>
            <F fp="vitals.height"  label="Height" />
            <F fp="vitals.weight"  label="Weight" />
            <F fp="vitals.bmi"     label="BMI" />
          </KVGrid>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "#888", fontFamily: "'DM Mono', monospace",
            marginTop: 12, marginBottom: 6 }}>
            Contact & Insurance
          </div>
          <KVGrid>
            <F fp="demographics.contact_info.phone"   label="Phone" />
            <F fp="demographics.contact_info.email"   label="Email" />
            <F fp="demographics.contact_info.address" label="Address" />
            <F fp="demographics.insurance.provider"        label="Insurance Provider" />
            <F fp="demographics.insurance.policy_number"   label="Policy No." />
            <F fp="demographics.emergency_contact.name"    label="Emergency Contact" />
            <F fp="demographics.emergency_contact.relationship" label="Relationship" />
            <F fp="demographics.emergency_contact.phone"   label="Emergency Phone" />
          </KVGrid>

          {/* ══════════════════════════════════════════════ ALLERGIES ═══ */}
          <Heading>🚨 Allergies</Heading>
          {(rec.allergies || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>No allergies documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
              {(rec.allergies || []).map((a, i) => (
                <div key={i} style={{ background: "#fff8f8", border: "1px solid rgba(239,68,68,0.18)",
                  borderRadius: 8, padding: "8px 12px",
                  display: "grid", gridTemplateColumns: "2fr 2fr 1fr", gap: 8 }}>
                  <div>
                    <Label>Substance</Label>
                    <input value={a.substance || ""} onChange={(e) => updItemField("allergies", i, "substance", e.target.value)}
                      style={{ ...INPUT_BASE, ...pickS(`allergies.${i}.substance`) }} />
                  </div>
                  <div>
                    <Label>Reaction</Label>
                    <input value={a.reaction || ""} onChange={(e) => updItemField("allergies", i, "reaction", e.target.value)}
                      style={{ ...INPUT_BASE, ...(a.reaction ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Severity</Label>
                    <input value={a.severity || ""} onChange={(e) => updItemField("allergies", i, "severity", e.target.value)}
                      style={{ ...INPUT_BASE, ...(a.severity ? S.modified : S.normal) }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ═══════════════════════════════════════ CHIEF COMPLAINT ═══ */}
          <Heading>Chief Complaint</Heading>
          <F fp="chief_complaint.free_text" label="Complaint" multiline
             placeholder="Chief complaint free text…" />
          <KVGrid>
            <F fp="chief_complaint.onset"    label="Onset" />
            <F fp="chief_complaint.duration" label="Duration" />
            <F fp="chief_complaint.severity" label="Severity" />
            <F fp="chief_complaint.location" label="Location" />
          </KVGrid>

          {/* ══════════════════════════════════════════════════ HPI ═══ */}
          <Heading>History of Present Illness</Heading>
          {(rec.hpi || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>No HPI events documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
              {(rec.hpi || []).map((ev, i) => (
                <div key={i} style={{ background: "#fafafa", borderRadius: 8,
                  border: "1px solid rgba(0,0,0,0.07)", padding: "10px 12px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 8, marginBottom: 6 }}>
                    <div>
                      <Label>Symptom</Label>
                      <input value={ev.symptom || ""} onChange={(e) => updItemField("hpi", i, "symptom", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.symptom ? S.modified : S.normal) }} />
                    </div>
                    <div>
                      <Label>Onset</Label>
                      <input value={ev.onset || ""} onChange={(e) => updItemField("hpi", i, "onset", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.onset ? S.modified : S.normal) }} />
                    </div>
                    <div>
                      <Label>Progression</Label>
                      <input value={ev.progression || ""} onChange={(e) => updItemField("hpi", i, "progression", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.progression ? S.modified : S.normal) }} />
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                    <div>
                      <Label>Triggers</Label>
                      <input value={ev.triggers || ""} onChange={(e) => updItemField("hpi", i, "triggers", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.triggers ? S.modified : S.normal) }} />
                    </div>
                    <div>
                      <Label>Relieving</Label>
                      <input value={ev.relieving_factors || ""} onChange={(e) => updItemField("hpi", i, "relieving_factors", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.relieving_factors ? S.modified : S.normal) }} />
                    </div>
                    <div>
                      <Label>Associated Sx</Label>
                      <input value={ev.associated_symptoms || ""} onChange={(e) => updItemField("hpi", i, "associated_symptoms", e.target.value)}
                        style={{ ...INPUT_BASE, ...(ev.associated_symptoms ? S.modified : S.normal) }} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ══════════════════════════════════ PAST MEDICAL HISTORY ═══ */}
          <Heading>Past Medical History</Heading>
          <Label>Chronic Conditions</Label>
          {(rec.past_medical_history?.chronic_conditions || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>None documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
              {(rec.past_medical_history?.chronic_conditions || []).map((c, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "3fr 1fr 1fr",
                  gap: 8, background: "#fafafa", borderRadius: 6,
                  border: "1px solid rgba(0,0,0,0.06)", padding: "6px 10px" }}>
                  <div>
                    <Label>Condition</Label>
                    <input value={c.name || ""} onChange={(e) => updItemField("past_medical_history.chronic_conditions", i, "name", e.target.value)}
                      style={{ ...INPUT_BASE, ...(isLow(`pmh.chronic_conditions.${c.name}`) ? S.lowConf : c.name ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Status</Label>
                    <input value={c.status || ""} onChange={(e) => updItemField("past_medical_history.chronic_conditions", i, "status", e.target.value)}
                      style={{ ...INPUT_BASE, ...(c.status ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Onset Year</Label>
                    <input value={c.onset_year || ""} onChange={(e) => updItemField("past_medical_history.chronic_conditions", i, "onset_year", e.target.value)}
                      style={{ ...INPUT_BASE, ...(c.onset_year ? S.modified : S.normal) }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          <KVGrid>
            <div>
              <Label>Surgeries</Label>
              <textarea
                value={(rec.past_medical_history?.surgeries || []).map((s) => s.name || "").join("\n")}
                onChange={(e) => update("past_medical_history.surgeries", e.target.value.split("\n").map((s) => ({ name: s.trim() })).filter((s) => s.name))}
                placeholder="One surgery per line"
                style={{ ...TA_BASE, ...pickS("past_medical_history.surgeries") }} />
            </div>
            <div>
              <Label>Hospitalizations</Label>
              <textarea
                value={(rec.past_medical_history?.hospitalizations || []).map((h) => h.reason || "").join("\n")}
                onChange={(e) => update("past_medical_history.hospitalizations", e.target.value.split("\n").map((r) => ({ reason: r.trim() })).filter((r) => r.reason))}
                placeholder="One hospitalization per line"
                style={{ ...TA_BASE, ...pickS("past_medical_history.hospitalizations") }} />
            </div>
          </KVGrid>

          {/* ═══════════════════════════════════════════ MEDICATIONS ═══ */}
          <Heading>Medications</Heading>
          {(rec.medications || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>No medications documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
              {(rec.medications || []).map((m, i) => (
                <div key={i} style={{ background: "#fafafa", borderRadius: 8,
                  border: "1px solid rgba(0,0,0,0.07)", padding: "8px 12px",
                  display: "grid", gridTemplateColumns: "2fr 1fr 1fr 2fr", gap: 8 }}>
                  <div>
                    <Label>Drug</Label>
                    <input value={m.name || ""} onChange={(e) => updItemField("medications", i, "name", e.target.value)}
                      style={{ ...INPUT_BASE, ...(isLow(`medications.${m.name}`) ? S.lowConf : m.name ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Dose</Label>
                    <input value={m.dose || ""} onChange={(e) => updItemField("medications", i, "dose", e.target.value)}
                      style={{ ...INPUT_BASE, ...(m.dose ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Frequency</Label>
                    <input value={m.frequency || ""} onChange={(e) => updItemField("medications", i, "frequency", e.target.value)}
                      style={{ ...INPUT_BASE, ...(m.frequency ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Indication</Label>
                    <input value={m.indication || ""} onChange={(e) => updItemField("medications", i, "indication", e.target.value)}
                      style={{ ...INPUT_BASE, ...(m.indication ? S.modified : S.normal) }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ═══════════════════════════════════════ FAMILY HISTORY ═══ */}
          <Heading>Family History</Heading>
          {(rec.family_history || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>None documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
              {(rec.family_history || []).map((fh, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 3fr",
                  gap: 8, background: "#fafafa", borderRadius: 6,
                  border: "1px solid rgba(0,0,0,0.06)", padding: "6px 10px" }}>
                  <div>
                    <Label>Member</Label>
                    <input value={fh.member || ""} onChange={(e) => updItemField("family_history", i, "member", e.target.value)}
                      style={{ ...INPUT_BASE, ...(fh.member ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Conditions</Label>
                    <input
                      value={(fh.conditions || []).join(", ")}
                      onChange={(e) => updItemField("family_history", i, "conditions",
                        e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                      placeholder="Comma-separated"
                      style={{ ...INPUT_BASE, ...((fh.conditions || []).length > 0 ? S.modified : S.normal) }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ══════════════════════════════════════ SOCIAL HISTORY ═══ */}
          <Heading>Social History</Heading>
          <KVGrid>
            {["tobacco","alcohol","drug_use","occupation","exercise","diet"].map((k) => (
              <div key={k}>
                <Label>{k.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())}</Label>
                <input value={rec.social_history?.[k] || ""}
                  onChange={(e) => update(`social_history.${k}`, e.target.value)}
                  style={{ ...INPUT_BASE, ...pickS(`social_history.${k}`) }} />
              </div>
            ))}
          </KVGrid>

          {/* ══════════════════════════════════ REVIEW OF SYSTEMS ═════ */}
          <Heading>Review of Systems</Heading>
          <KVGrid>
            {["cardiovascular","respiratory","neurological","gastrointestinal",
              "musculoskeletal","dermatological","psychiatric","endocrine",
              "genitourinary","hematologic"].map((k) => (
              <div key={k}>
                <Label>{k.replace(/\b\w/g, (c) => c.toUpperCase())}</Label>
                <input value={rec.review_of_systems?.[k] || ""}
                  onChange={(e) => update(`review_of_systems.${k}`, e.target.value)}
                  placeholder="Not documented"
                  style={{ ...INPUT_BASE, ...pickS(`review_of_systems.${k}`) }} />
              </div>
            ))}
          </KVGrid>

          {/* ══════════════════════════════════════════════ VITALS ═══ */}
          <Heading>Vitals</Heading>
          <KVGrid>
            {[
              ["blood_pressure","Blood Pressure"], ["heart_rate","Heart Rate"],
              ["respiratory_rate","Respiratory Rate"], ["temperature","Temperature"],
              ["spo2","O₂ Saturation"], ["height","Height"],
              ["weight","Weight"], ["bmi","BMI"],
            ].map(([k, label]) => (
              <div key={k}>
                <Label>{label}</Label>
                <input
                  value={(typeof rec.vitals === "object" && !Array.isArray(rec.vitals))
                    ? rec.vitals?.[k] || "" : ""}
                  onChange={(e) => update(`vitals.${k}`, e.target.value)}
                  style={{ ...INPUT_BASE, ...pickS(`vitals.${k}`) }}
                  title={conTip(`vitals.${k}`)} />
              </div>
            ))}
          </KVGrid>

          {/* ══════════════════════════════════════ PHYSICAL EXAM ═════ */}
          <Heading>Physical Exam</Heading>
          <KVGrid>
            {["general","cardiovascular","respiratory","neurological",
              "abdomen","musculoskeletal","skin","head_neck"].map((k) => (
              <div key={k}>
                <Label>{k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}</Label>
                <input value={rec.physical_exam?.[k] || ""}
                  onChange={(e) => update(`physical_exam.${k}`, e.target.value)}
                  placeholder="Not documented"
                  style={{ ...INPUT_BASE, ...pickS(`physical_exam.${k}`) }} />
              </div>
            ))}
          </KVGrid>

          {/* ═══════════════════════════════════════════════ LABS ═════ */}
          <Heading>Laboratory Results</Heading>
          {(rec.labs || []).length === 0 ? (
            <p style={{ fontSize: 12, color: "#bbb", fontStyle: "italic", margin: "0 0 8px" }}>No lab results documented</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
              {(rec.labs || []).map((lab, i) => (
                <div key={i} style={{ background: "#fafafa", borderRadius: 8,
                  border: lab.abnormal ? "1px solid rgba(239,68,68,0.25)" : "1px solid rgba(0,0,0,0.07)",
                  padding: "8px 12px",
                  display: "grid", gridTemplateColumns: "3fr 2fr 1fr 2fr 2fr", gap: 8 }}>
                  <div>
                    <Label>Test</Label>
                    <input value={lab.test || ""} onChange={(e) => updItemField("labs", i, "test", e.target.value)}
                      style={{ ...INPUT_BASE, ...(lab.test ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Value {lab.abnormal ? "⚠" : ""}</Label>
                    <input value={lab.value || ""}
                      onChange={(e) => updItemField("labs", i, "value", e.target.value)}
                      style={{ ...INPUT_BASE, ...(lab.abnormal
                        ? { ...S.conflict, color: "#dc2626", fontWeight: 600 }
                        : lab.value ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Unit</Label>
                    <input value={lab.unit || ""} onChange={(e) => updItemField("labs", i, "unit", e.target.value)}
                      style={{ ...INPUT_BASE, ...(lab.unit ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Reference</Label>
                    <input value={lab.reference_range || ""} onChange={(e) => updItemField("labs", i, "reference_range", e.target.value)}
                      style={{ ...INPUT_BASE, ...(lab.reference_range ? S.modified : S.normal) }} />
                  </div>
                  <div>
                    <Label>Date</Label>
                    <input value={lab.date || ""} onChange={(e) => updItemField("labs", i, "date", e.target.value)}
                      style={{ ...INPUT_BASE, ...(lab.date ? S.modified : S.normal) }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ═══════════════════════════════════════ PROBLEM LIST ═════ */}
          <Heading>Problem List</Heading>
          <textarea
            value={listToText(rec.problem_list, "name")}
            onChange={(e) => update("problem_list", textToList(e.target.value, "name"))}
            placeholder="One problem per line"
            style={{ ...TA_BASE, ...pickS("problem_list"), width: "100%" }} />

          {/* ════════════════════════════════════════ RISK FACTORS ═════ */}
          <Heading>Risk Factors</Heading>
          <textarea
            value={listToText(rec.risk_factors, "name")}
            onChange={(e) => update("risk_factors", textToList(e.target.value, "name"))}
            placeholder="One risk factor per line"
            style={{ ...TA_BASE, ...pickS("risk_factors"), width: "100%" }} />

          {/* ══════════════════════════════════════════ ASSESSMENT ═════ */}
          <Heading>Assessment</Heading>
          <div>
            <Label>Clinical Reasoning</Label>
            <textarea value={rec.assessment?.clinical_reasoning || ""}
              onChange={(e) => update("assessment.clinical_reasoning", e.target.value)}
              placeholder="Clinical reasoning…"
              style={{ ...TA_BASE, ...pickS("assessment.clinical_reasoning"), width: "100%" }} />
          </div>
          <KVGrid>
            <div>
              <Label>Likely Diagnoses</Label>
              <textarea
                value={(rec.assessment?.likely_diagnoses || []).join("\n")}
                onChange={(e) => update("assessment.likely_diagnoses",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("assessment.likely_diagnoses") }} />
            </div>
            <div>
              <Label>Differential Diagnoses</Label>
              <textarea
                value={(rec.assessment?.differential_diagnoses || []).join("\n")}
                onChange={(e) => update("assessment.differential_diagnoses",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("assessment.differential_diagnoses") }} />
            </div>
          </KVGrid>

          {/* ══════════════════════════════════════════════ PLAN ══════ */}
          <Heading>Plan</Heading>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 14px" }}>
            <div>
              <Label>Medications Prescribed</Label>
              <textarea
                value={(rec.plan?.medications_prescribed || []).join("\n")}
                onChange={(e) => update("plan.medications_prescribed",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("plan.medications_prescribed") }} />
            </div>
            <div>
              <Label>Tests Ordered</Label>
              <textarea
                value={(rec.plan?.tests_ordered || []).join("\n")}
                onChange={(e) => update("plan.tests_ordered",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("plan.tests_ordered") }} />
            </div>
            <div>
              <Label>Lifestyle Recommendations</Label>
              <textarea
                value={(rec.plan?.lifestyle_recommendations || []).join("\n")}
                onChange={(e) => update("plan.lifestyle_recommendations",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("plan.lifestyle_recommendations") }} />
            </div>
            <div>
              <Label>Referrals</Label>
              <textarea
                value={(rec.plan?.referrals || []).join("\n")}
                onChange={(e) => update("plan.referrals",
                  e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                placeholder="One per line"
                style={{ ...TA_BASE, ...pickS("plan.referrals") }} />
            </div>
          </div>
          <div style={{ marginTop: 6 }}>
            <Label>Follow-up</Label>
            <input value={rec.plan?.follow_up || ""}
              onChange={(e) => update("plan.follow_up", e.target.value)}
              style={{ ...INPUT_BASE, ...pickS("plan.follow_up"), width: "100%" }} />
          </div>

          {/* Legend */}
          <div style={{ display: "flex", gap: 16, marginTop: 24, paddingTop: 12,
            borderTop: "1px solid rgba(0,0,0,0.06)", flexWrap: "wrap" }}>
            {[
              { bg: "#eff6ff", border: "#3b82f6", label: "Extracted / modified field" },
              { bg: "#fefce8", border: "#eab308", label: "Uncertain (< 70% confidence)" },
              { bg: "#fef2f2", border: "#ef4444", label: "Conflict — DB vs extracted (hover for details)" },
              { bg: "#fff8f8", border: "rgba(239,68,68,0.18)", label: "Abnormal lab value" },
            ].map((l) => (
              <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 16, height: 16, borderRadius: 3,
                  background: l.bg, border: `1px solid ${l.border}` }} />
                <span style={{ fontSize: 10, color: "#888", fontFamily: "'DM Mono', monospace" }}>{l.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
