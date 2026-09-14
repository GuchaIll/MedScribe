/**
 * Helpers for the post-pipeline "Review patient record changes" card.
 *
 * Ports buildReviewFields + classifyField from
 * client/medscribe/src/components/MedicalTranscription.jsx. We walk a small
 * set of top-level StructuredRecord sections, render each as one row, and
 * tag the row with a status derived from the pipeline's validation_report.
 */

export type ReviewFieldStatus = "ok" | "warning" | "conflict" | "unchanged";

export type ReviewField = {
  title: string;
  /** String preview of the field value. Multi-line allowed. */
  value: string;
  status: ReviewFieldStatus;
  /** Human-readable explanation displayed below the value when present. */
  reason?: string;
};

/**
 * Subset of validation_report fields we read. Backend shape is loose
 * (server/app/agents/nodes/validate.py); we accept what's there.
 */
export type ValidationReport = {
  schema_errors?: string[];
  missing_fields?: string[];
  conflicts?: Array<string | { field?: string; message?: string }>;
  contradictions?: Array<string | { field?: string; message?: string }>;
  warnings?: Array<string | { field?: string; message?: string }>;
  needs_review?: boolean;
  [k: string]: unknown;
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_");

const flattenEntries = (
  arr: Array<string | { field?: string; message?: string }> | undefined,
): Array<{ field: string; message?: string }> => {
  return (arr ?? [])
    .map((e) =>
      typeof e === "string"
        ? { field: "", message: e }
        : { field: e.field ?? "", message: e.message },
    );
};

const mentions = (
  haystack: Array<{ field: string; message?: string }>,
  needle: string,
): { field: string; message?: string } | undefined => {
  const n = norm(needle);
  return haystack.find(
    (e) =>
      (e.field && norm(e.field).includes(n)) ||
      (e.message && norm(e.message).includes(n)),
  );
};

export const classifyField = (
  title: string,
  raw: unknown,
  validation: ValidationReport | null | undefined,
): { status: ReviewFieldStatus; reason?: string } => {
  const conflicts = flattenEntries([
    ...(validation?.conflicts ?? []),
    ...(validation?.contradictions ?? []),
  ]);
  const warnings = flattenEntries(validation?.warnings);

  const conflictHit = mentions(conflicts, title);
  if (conflictHit) {
    return {
      status: "conflict",
      reason:
        conflictHit.message ?? "Conflicts with existing record — please verify",
    };
  }
  const warnHit = mentions(warnings, title);
  if (warnHit) {
    return {
      status: "warning",
      reason: warnHit.message ?? "Low confidence — please confirm",
    };
  }

  const present =
    raw != null && raw !== "" && !(Array.isArray(raw) && raw.length === 0);
  if (present) {
    return { status: "ok", reason: "Updated from session transcript" };
  }
  return { status: "unchanged" };
};

const renderValue = (raw: unknown): string => {
  if (raw == null) return "—";
  if (typeof raw === "string") return raw.trim() || "—";
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  if (Array.isArray(raw)) {
    if (raw.length === 0) return "—";
    return raw
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const rec = item as Record<string, unknown>;
          return (
            (rec.name as string) ||
            (rec.substance as string) ||
            (rec.description as string) ||
            JSON.stringify(rec)
          );
        }
        return String(item);
      })
      .join("\n");
  }
  if (typeof raw === "object") {
    const entries = Object.entries(raw as Record<string, unknown>).filter(
      ([, v]) => v != null && v !== "" && v !== "None",
    );
    if (entries.length === 0) return "—";
    return entries.map(([k, v]) => `${k}: ${renderValue(v)}`).join("\n");
  }
  return String(raw);
};

export type ReviewSourceRecord = Record<string, unknown>;

const SECTIONS: Array<{ title: string; pick: (r: ReviewSourceRecord) => unknown; gated?: boolean }> = [
  { title: "Patient Info", pick: (r) => r.patient_info ?? r.demographics, gated: true },
  { title: "Chief Complaint", pick: (r) => r.chief_complaint },
  { title: "History of Present Illness", pick: (r) => r.history_of_present_illness ?? r.hpi },
  { title: "Medications", pick: (r) => r.medications },
  { title: "Allergies", pick: (r) => r.allergies },
  { title: "Assessment", pick: (r) => r.assessment },
  { title: "Plan", pick: (r) => r.plan },
  { title: "Vitals", pick: (r) => r.vitals, gated: true },
  { title: "Physical Exam", pick: (r) => r.physical_exam, gated: true },
  { title: "Diagnosis", pick: (r) => r.diagnosis, gated: true },
  { title: "Follow-Up", pick: (r) => r.follow_up ?? (r.plan as Record<string, unknown> | undefined)?.follow_up, gated: true },
];

/**
 * Walk the structured record and produce one ReviewField per top-level
 * clinical section the LLM might have touched. Gated sections only appear
 * when populated, so empty records stay short.
 */
export const buildReviewFields = (
  record: ReviewSourceRecord | null | undefined,
  validation: ValidationReport | null | undefined,
): ReviewField[] => {
  if (!record) return [];
  const out: ReviewField[] = [];
  for (const s of SECTIONS) {
    const raw = s.pick(record);
    if (s.gated && (raw == null || raw === "")) continue;
    const { status, reason } = classifyField(s.title, raw, validation);
    out.push({ title: s.title, value: renderValue(raw), status, reason });
  }
  return out;
};
