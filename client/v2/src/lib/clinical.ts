/**
 * Shared clinical data types + helpers used across the OCR review surface.
 *
 * Mirrors what client/medscribe/src/components/upload/DocumentViewPanel.jsx
 * built inline. Pulled into a separate module so FieldComparator,
 * ConflictResolver, and any future pipeline review components can share it.
 */

/* ── Status tokens ──────────────────────────────────────────────────────── */

export type FieldStatus = "normal" | "modified" | "lowConf" | "conflict";

/** Confidence threshold below which a field is rendered as uncertain. */
export const LOW_CONF = 0.7;

/**
 * Tailwind class strings for each status. The original codebase used
 * inline-style hex backgrounds; these correspond 1:1 but plug into the rest of
 * v2's tonal system (compare with components/clinical/_shared.tsx::toneClasses).
 */
export const STATUS_CLASSES: Record<FieldStatus, string> = {
  normal: "bg-white border-zinc-200",
  modified: "bg-blue-50 border-blue-400",
  lowConf: "bg-yellow-50 border-yellow-400",
  conflict: "bg-rose-50 border-rose-400",
};

export const STATUS_LABELS: Record<FieldStatus, string> = {
  normal: "Unchanged",
  modified: "Extracted",
  lowConf: "Uncertain",
  conflict: "Conflict",
};

/* ── Structured record types ─────────────────────────────────────────────── */

export type Conflict = {
  field: string;
  db_value: unknown;
  extracted_value: unknown;
  resolution?: "db" | "extracted" | "manual" | null;
  resolved_value?: unknown;
};

export type LowConfidence = {
  field: string;
  confidence: number;
};

export type Allergy = {
  substance?: string;
  reaction?: string;
  severity?: string;
};

export type Medication = {
  name?: string;
  dose?: string;
  frequency?: string;
  route?: string;
  indication?: string;
};

export type ChronicCondition = { name?: string; status?: string; onset_year?: string };

export type HpiEvent = {
  symptom?: string;
  onset?: string;
  progression?: string;
  triggers?: string;
  relieving_factors?: string;
  associated_symptoms?: string;
};

export type LabResult = {
  test?: string;
  value?: string;
  unit?: string;
  reference_range?: string;
  date?: string;
  abnormal?: boolean;
};

export type FamilyHistoryEntry = { member?: string; conditions?: string[] };

export type StructuredRecord = {
  demographics: {
    full_name?: string;
    date_of_birth?: string;
    age?: string;
    sex?: string;
    gender?: string;
    mrn?: string;
    contact_info: { phone?: string; email?: string; address?: string };
    insurance: { provider?: string; policy_number?: string };
    emergency_contact: { name?: string; relationship?: string; phone?: string };
  };
  chief_complaint: {
    free_text?: string;
    onset?: string;
    duration?: string;
    severity?: string;
    location?: string;
  };
  hpi: HpiEvent[];
  past_medical_history: {
    chronic_conditions: ChronicCondition[];
    surgeries: Array<{ name?: string }>;
    hospitalizations: Array<{ reason?: string }>;
  };
  medications: Medication[];
  allergies: Allergy[];
  family_history: FamilyHistoryEntry[];
  social_history: Record<string, string>;
  review_of_systems: Record<string, string>;
  vitals: Record<string, string>;
  physical_exam: Record<string, string>;
  labs: LabResult[];
  problem_list: Array<{ name?: string }>;
  risk_factors: Array<{ name?: string }>;
  assessment: {
    likely_diagnoses?: string[];
    differential_diagnoses?: string[];
    clinical_reasoning?: string;
  };
  plan: {
    medications_prescribed?: string[];
    tests_ordered?: string[];
    lifestyle_recommendations?: string[];
    referrals?: string[];
    follow_up?: string;
  };
  _conflicts?: Conflict[];
  _low_confidence?: LowConfidence[];
  _db_seeded_fields?: string[];
};

export const EMPTY_RECORD: StructuredRecord = {
  demographics: {
    full_name: "",
    date_of_birth: "",
    age: "",
    sex: "",
    gender: "",
    mrn: "",
    contact_info: { phone: "", email: "", address: "" },
    insurance: { provider: "", policy_number: "" },
    emergency_contact: { name: "", relationship: "", phone: "" },
  },
  chief_complaint: { free_text: "", onset: "", duration: "", severity: "", location: "" },
  hpi: [],
  past_medical_history: { chronic_conditions: [], surgeries: [], hospitalizations: [] },
  medications: [],
  allergies: [],
  family_history: [],
  social_history: {
    tobacco: "",
    alcohol: "",
    drug_use: "",
    occupation: "",
    exercise: "",
    diet: "",
  },
  review_of_systems: {},
  vitals: {
    blood_pressure: "",
    heart_rate: "",
    respiratory_rate: "",
    temperature: "",
    spo2: "",
    height: "",
    weight: "",
    bmi: "",
  },
  physical_exam: {},
  labs: [],
  problem_list: [],
  risk_factors: [],
  assessment: { likely_diagnoses: [], differential_diagnoses: [], clinical_reasoning: "" },
  plan: {
    medications_prescribed: [],
    tests_ordered: [],
    lifestyle_recommendations: [],
    referrals: [],
    follow_up: "",
  },
  _conflicts: [],
  _low_confidence: [],
};

/* ── Immutable update helpers (dotted-path) ──────────────────────────────── */

export function setPath<T extends Record<string, unknown>>(obj: T, dotPath: string, value: unknown): T {
  const copy = JSON.parse(JSON.stringify(obj)) as Record<string, unknown>;
  const parts = dotPath.split(".");
  let cur = copy;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    if (cur[key] == null) cur[key] = {};
    cur = cur[key] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
  return copy as T;
}

export function setListField<T extends Record<string, unknown>>(
  obj: T,
  dotPath: string,
  idx: number,
  field: string,
  value: unknown,
): T {
  const copy = JSON.parse(JSON.stringify(obj)) as Record<string, unknown>;
  const parts = dotPath.split(".");
  let arr: unknown = copy;
  for (const p of parts) arr = (arr as Record<string, unknown>)[p];
  const list = arr as Array<Record<string, unknown>> | undefined;
  if (list?.[idx] != null) list[idx][field] = value;
  return copy as T;
}

/** Read a value out of an object at a dotted path, returning undefined for misses. */
export function getPath(obj: unknown, dotPath: string): unknown {
  return dotPath.split(".").reduce<unknown>((o, k) => {
    if (o == null || typeof o !== "object") return undefined;
    return (o as Record<string, unknown>)[k];
  }, obj);
}

/* ── Field-change normaliser (flat list → structured record) ─────────────── */

export type FieldChange = { field_name: string; value: unknown };

/**
 * Build a partial StructuredRecord from the backend's flat field_changes list.
 * Mirrors server/app/core/ocr.py::_ocr_fields_to_structured_record so the UI
 * can render OCR results even if the consolidated structured_record hasn't
 * been merged yet.
 */
export function buildRecordFromFieldChanges(
  fieldChanges: FieldChange[] | undefined | null,
): StructuredRecord | null {
  if (!fieldChanges || fieldChanges.length === 0) return null;
  const r: StructuredRecord = JSON.parse(JSON.stringify(EMPTY_RECORD));
  for (const fc of fieldChanges) {
    const v = fc.value;
    if (v == null || v === "") continue;
    const n = (fc.field_name || "").toLowerCase();
    const s = typeof v === "string" ? v : String(v);
    if (n === "patient_name" || n === "full_name") r.demographics.full_name = s;
    else if (n === "date_of_birth" || n === "dob") r.demographics.date_of_birth = s;
    else if (n === "age") r.demographics.age = s;
    else if (n === "sex") r.demographics.sex = s;
    else if (n === "gender") {
      r.demographics.gender = s;
      if (!r.demographics.sex) r.demographics.sex = s;
    } else if (n === "mrn") r.demographics.mrn = s;
    else if (n === "phone") r.demographics.contact_info.phone = s;
    else if (n === "email") r.demographics.contact_info.email = s;
    else if (n === "address") r.demographics.contact_info.address = s;
    else if (n === "insurance_provider") r.demographics.insurance.provider = s;
    else if (n === "insurance_policy") r.demographics.insurance.policy_number = s;
    else if (n === "chief_complaint" || n === "cc") r.chief_complaint.free_text = s;
    else if (n === "onset") r.chief_complaint.onset = s;
    else if (n === "duration") r.chief_complaint.duration = s;
    else if (n === "severity") r.chief_complaint.severity = s;
    else if (n === "blood_pressure" || n === "bp") r.vitals.blood_pressure = s;
    else if (n === "heart_rate" || n === "hr" || n === "pulse") r.vitals.heart_rate = s;
    else if (n === "respiratory_rate" || n === "rr") r.vitals.respiratory_rate = s;
    else if (n === "temperature" || n === "temp") r.vitals.temperature = s;
    else if (n === "spo2" || n === "oxygen_saturation") r.vitals.spo2 = s;
    else if (n === "height") r.vitals.height = s;
    else if (n === "weight") r.vitals.weight = s;
    else if (n === "bmi") r.vitals.bmi = s;
    else if (n === "lab_result") {
      r.labs.push(typeof v === "object" ? (v as LabResult) : { test: s, value: "", unit: "" });
    } else if (n === "medication") {
      r.medications.push(
        typeof v === "object"
          ? (v as Medication)
          : { name: s, dose: "", frequency: "", route: "" },
      );
    } else if (n === "allergy") {
      r.allergies.push(
        typeof v === "object" ? (v as Allergy) : { substance: s, reaction: "", severity: "" },
      );
    } else if (n === "chronic_condition") {
      r.past_medical_history.chronic_conditions.push(
        typeof v === "object" ? (v as ChronicCondition) : { name: s },
      );
    } else if (n === "problem" || n === "diagnosis") {
      r.problem_list.push(typeof v === "object" ? (v as { name?: string }) : { name: s });
    } else if (n === "risk_factor") {
      r.risk_factors.push(typeof v === "object" ? (v as { name?: string }) : { name: s });
    } else if (n === "tobacco" || n === "smoking") r.social_history.tobacco = s;
    else if (n === "alcohol") r.social_history.alcohol = s;
    else if (n === "occupation") r.social_history.occupation = s;
    else if (n === "assessment" || n === "impression") r.assessment.clinical_reasoning = s;
    else if (n === "follow_up") r.plan.follow_up = s;
  }
  return r;
}

/* ── Summary builder ─────────────────────────────────────────────────────── */

export function buildSummary(rec: StructuredRecord | null | undefined): string | null {
  if (!rec) return null;
  const demo = rec.demographics || {};
  const name = demo.full_name || "The patient";
  const dob = demo.date_of_birth ? ` (DOB ${demo.date_of_birth})` : "";
  const cc = rec.chief_complaint?.free_text;
  const meds = (rec.medications || []).length;
  const algs = (rec.allergies || []).length;
  const pmhList = (rec.past_medical_history?.chronic_conditions || [])
    .slice(0, 3)
    .map((c) => c.name || "")
    .filter(Boolean);
  const assessment =
    rec.assessment?.clinical_reasoning ||
    (rec.assessment?.likely_diagnoses || []).join(", ");
  const followUp = rec.plan?.follow_up;

  const sentences: string[] = [];
  let s1 = `${name}${dob} presents`;
  if (cc) s1 += ` with ${cc.replace(/[.!?]+$/, "")}`;
  sentences.push(`${s1}.`);

  if (pmhList.length > 0) {
    const total = (rec.past_medical_history?.chronic_conditions || []).length;
    sentences.push(
      `PMH includes ${pmhList.join(", ")}${total > 3 ? ", and others" : ""}.`,
    );
  }
  if (meds > 0 || algs > 0) {
    sentences.push(
      `Currently on ${meds} medication${meds !== 1 ? "s" : ""}` +
        (algs > 0 ? ` with ${algs} documented allerg${algs !== 1 ? "ies" : "y"}` : "") +
        ".",
    );
  }
  if (assessment) sentences.push(`Assessment: ${assessment}.`);
  else if (followUp) sentences.push(`Follow-up: ${followUp}.`);

  return sentences.slice(0, 4).join(" ");
}

/* ── Field status detection ──────────────────────────────────────────────── */

/** Memo-friendly set/map builder for the three status overlays. */
export function buildStatusIndex(rec: StructuredRecord | null | undefined) {
  const lowConfSet = new Set((rec?._low_confidence || []).map((l) => l.field));
  const conflictMap = new Map<string, Conflict>();
  (rec?._conflicts || []).forEach((c) => conflictMap.set(c.field, c));

  const modifiedSet = new Set<string>(rec?._db_seeded_fields || []);
  const walk = (obj: unknown, prefix: string) => {
    if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return;
    for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
      if (key.startsWith("_")) continue;
      const fp = prefix ? `${prefix}.${key}` : key;
      if (typeof val === "string" && val.trim() !== "") modifiedSet.add(fp);
      else if (typeof val === "number") modifiedSet.add(fp);
      else if (Array.isArray(val) && val.length > 0) modifiedSet.add(fp);
      else if (typeof val === "object" && val !== null) walk(val, fp);
    }
  };
  walk(rec, "");

  return {
    lowConfSet,
    conflictMap,
    modifiedSet,
    statusFor(fp: string): FieldStatus {
      if (conflictMap.has(fp)) return "conflict";
      if (lowConfSet.has(fp)) return "lowConf";
      if (modifiedSet.has(fp)) return "modified";
      return "normal";
    },
  };
}
