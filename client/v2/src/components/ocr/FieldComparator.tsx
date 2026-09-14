import { useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  buildStatusIndex,
  getPath,
  setListField,
  setPath,
  STATUS_CLASSES,
  type FieldStatus,
  type StructuredRecord,
} from "@/lib/clinical";
import { Field, FieldLabel, InlineField, KVGrid, SectionHeading, SubHeading } from "./Field";

const ROS_KEYS = [
  "cardiovascular",
  "respiratory",
  "neurological",
  "gastrointestinal",
  "musculoskeletal",
  "dermatological",
  "psychiatric",
  "endocrine",
  "genitourinary",
  "hematologic",
] as const;

const PE_KEYS = [
  "general",
  "cardiovascular",
  "respiratory",
  "neurological",
  "abdomen",
  "musculoskeletal",
  "skin",
  "head_neck",
] as const;

const SOCIAL_KEYS = ["tobacco", "alcohol", "drug_use", "occupation", "exercise", "diet"] as const;

const VITAL_KEYS: Array<[string, string]> = [
  ["blood_pressure", "Blood Pressure"],
  ["heart_rate", "Heart Rate"],
  ["respiratory_rate", "Respiratory Rate"],
  ["temperature", "Temperature"],
  ["spo2", "O₂ Saturation"],
  ["height", "Height"],
  ["weight", "Weight"],
  ["bmi", "BMI"],
];

const titleCase = (s: string) =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const displayVal = (raw: unknown): string => {
  if (raw == null) return "";
  if (typeof raw === "string") return raw;
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  if (Array.isArray(raw)) {
    return raw.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join(", ");
  }
  if (typeof raw === "object") {
    return Object.entries(raw as Record<string, unknown>)
      .filter(([, v]) => v != null && v !== "" && v !== "None")
      .map(([k, v]) => `${k}: ${v}`)
      .join(", ");
  }
  return String(raw);
};

const linesToList = <K extends string>(text: string, key: K): Array<Record<K, string>> =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((name) => ({ [key]: name } as Record<K, string>));

const listToLines = <T extends Record<string, unknown>>(arr: T[] | undefined, key: keyof T): string =>
  (arr ?? []).map((i) => (typeof i === "string" ? i : (i?.[key] as string) ?? "")).join("\n");

const arrayJoin = (arr: string[] | undefined) => (arr ?? []).join("\n");
const arraySplit = (s: string) =>
  s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export type FieldComparatorProps = {
  record: StructuredRecord;
  onChange: (next: StructuredRecord) => void;
};

/**
 * Editable view of a StructuredRecord. Status colours per field come from
 * `buildStatusIndex` against the record's _conflicts / _low_confidence /
 * _db_seeded_fields markers.
 */
export const FieldComparator = ({ record, onChange }: FieldComparatorProps) => {
  const status = useMemo(() => buildStatusIndex(record), [record]);

  const update = useCallback(
    (path: string, value: unknown) => {
      onChange(setPath(record, path, value));
    },
    [record, onChange],
  );

  const updListField = useCallback(
    (listPath: string, idx: number, field: string, value: unknown) => {
      onChange(setListField(record, listPath, idx, field, value));
    },
    [record, onChange],
  );

  /** Wrapper for primitive string fields keyed by dotted path. */
  const F = (props: { fp: string; label: string; multiline?: boolean; placeholder?: string }) => {
    const raw = getPath(record, props.fp);
    return (
      <Field
        label={props.label}
        value={displayVal(raw)}
        onChange={(v) => update(props.fp, v)}
        multiline={props.multiline}
        placeholder={props.placeholder}
        status={status.statusFor(props.fp)}
        conflict={status.conflictMap.get(props.fp)}
      />
    );
  };

  const pmh = record.past_medical_history;
  const empty = "italic text-foreground/40 text-[12px] mb-2";

  return (
    <div className="space-y-1">
      {/* ── Demographics ───────────────────────────────────────────────── */}
      <SectionHeading>Demographics</SectionHeading>
      <KVGrid>
        <F fp="demographics.full_name" label="Full Name" />
        <F fp="demographics.date_of_birth" label="Date of Birth" placeholder="YYYY-MM-DD" />
        <F fp="demographics.age" label="Age" placeholder="e.g. 45" />
        <F fp="demographics.gender" label="Gender" />
        <F fp="demographics.sex" label="Biological Sex" />
        <F fp="demographics.mrn" label="MRN" />
      </KVGrid>

      <SubHeading>Anthropometrics</SubHeading>
      <KVGrid>
        <F fp="vitals.height" label="Height" />
        <F fp="vitals.weight" label="Weight" />
        <F fp="vitals.bmi" label="BMI" />
      </KVGrid>

      <SubHeading>Contact &amp; Insurance</SubHeading>
      <KVGrid>
        <F fp="demographics.contact_info.phone" label="Phone" />
        <F fp="demographics.contact_info.email" label="Email" />
        <F fp="demographics.contact_info.address" label="Address" />
        <F fp="demographics.insurance.provider" label="Insurance Provider" />
        <F fp="demographics.insurance.policy_number" label="Policy No." />
        <F fp="demographics.emergency_contact.name" label="Emergency Contact" />
        <F fp="demographics.emergency_contact.relationship" label="Relationship" />
        <F fp="demographics.emergency_contact.phone" label="Emergency Phone" />
      </KVGrid>

      {/* ── Allergies ──────────────────────────────────────────────────── */}
      <SectionHeading>Allergies</SectionHeading>
      {(record.allergies || []).length === 0 ? (
        <p className={empty}>No allergies documented</p>
      ) : (
        <div className="mb-2 flex flex-col gap-2">
          {(record.allergies || []).map((a, i) => (
            <div
              key={i}
              className="grid grid-cols-[2fr_2fr_1fr] gap-2 rounded-lg border border-rose-200/70 bg-rose-50/60 px-3 py-2"
            >
              <div>
                <FieldLabel>Substance</FieldLabel>
                <InlineField
                  value={a.substance ?? ""}
                  onChange={(v) => updListField("allergies", i, "substance", v)}
                  status={status.statusFor(`allergies.${i}.substance`)}
                />
              </div>
              <div>
                <FieldLabel>Reaction</FieldLabel>
                <InlineField
                  value={a.reaction ?? ""}
                  onChange={(v) => updListField("allergies", i, "reaction", v)}
                  status={a.reaction ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Severity</FieldLabel>
                <InlineField
                  value={a.severity ?? ""}
                  onChange={(v) => updListField("allergies", i, "severity", v)}
                  status={a.severity ? "modified" : "normal"}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Chief complaint ────────────────────────────────────────────── */}
      <SectionHeading>Chief Complaint</SectionHeading>
      <F
        fp="chief_complaint.free_text"
        label="Complaint"
        multiline
        placeholder="Chief complaint free text…"
      />
      <KVGrid>
        <F fp="chief_complaint.onset" label="Onset" />
        <F fp="chief_complaint.duration" label="Duration" />
        <F fp="chief_complaint.severity" label="Severity" />
        <F fp="chief_complaint.location" label="Location" />
      </KVGrid>

      {/* ── HPI ────────────────────────────────────────────────────────── */}
      <SectionHeading>History of Present Illness</SectionHeading>
      {(record.hpi || []).length === 0 ? (
        <p className={empty}>No HPI events documented</p>
      ) : (
        <div className="mb-2 flex flex-col gap-2">
          {(record.hpi || []).map((ev, i) => (
            <div key={i} className="rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-2">
              <div className="mb-2 grid grid-cols-[2fr_1fr_1fr] gap-2">
                <div>
                  <FieldLabel>Symptom</FieldLabel>
                  <InlineField
                    value={ev.symptom ?? ""}
                    onChange={(v) => updListField("hpi", i, "symptom", v)}
                    status={ev.symptom ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Onset</FieldLabel>
                  <InlineField
                    value={ev.onset ?? ""}
                    onChange={(v) => updListField("hpi", i, "onset", v)}
                    status={ev.onset ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Progression</FieldLabel>
                  <InlineField
                    value={ev.progression ?? ""}
                    onChange={(v) => updListField("hpi", i, "progression", v)}
                    status={ev.progression ? "modified" : "normal"}
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <FieldLabel>Triggers</FieldLabel>
                  <InlineField
                    value={ev.triggers ?? ""}
                    onChange={(v) => updListField("hpi", i, "triggers", v)}
                    status={ev.triggers ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Relieving</FieldLabel>
                  <InlineField
                    value={ev.relieving_factors ?? ""}
                    onChange={(v) => updListField("hpi", i, "relieving_factors", v)}
                    status={ev.relieving_factors ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Associated Sx</FieldLabel>
                  <InlineField
                    value={ev.associated_symptoms ?? ""}
                    onChange={(v) => updListField("hpi", i, "associated_symptoms", v)}
                    status={ev.associated_symptoms ? "modified" : "normal"}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Past medical history ───────────────────────────────────────── */}
      <SectionHeading>Past Medical History</SectionHeading>
      <FieldLabel>Chronic Conditions</FieldLabel>
      {(pmh?.chronic_conditions || []).length === 0 ? (
        <p className={empty}>None documented</p>
      ) : (
        <div className="mb-3 flex flex-col gap-1.5">
          {(pmh?.chronic_conditions || []).map((c, i) => (
            <div
              key={i}
              className="grid grid-cols-[3fr_1fr_1fr] gap-2 rounded-md border border-zinc-200 bg-zinc-50/70 px-2.5 py-2"
            >
              <div>
                <FieldLabel>Condition</FieldLabel>
                <InlineField
                  value={c.name ?? ""}
                  onChange={(v) =>
                    updListField("past_medical_history.chronic_conditions", i, "name", v)
                  }
                  status={c.name ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Status</FieldLabel>
                <InlineField
                  value={c.status ?? ""}
                  onChange={(v) =>
                    updListField("past_medical_history.chronic_conditions", i, "status", v)
                  }
                  status={c.status ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Onset Year</FieldLabel>
                <InlineField
                  value={c.onset_year ?? ""}
                  onChange={(v) =>
                    updListField("past_medical_history.chronic_conditions", i, "onset_year", v)
                  }
                  status={c.onset_year ? "modified" : "normal"}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <KVGrid>
        <Field
          label="Surgeries"
          multiline
          placeholder="One surgery per line"
          value={listToLines(pmh?.surgeries, "name")}
          onChange={(v) => update("past_medical_history.surgeries", linesToList(v, "name"))}
          status={status.statusFor("past_medical_history.surgeries")}
        />
        <Field
          label="Hospitalizations"
          multiline
          placeholder="One hospitalization per line"
          value={listToLines(pmh?.hospitalizations, "reason")}
          onChange={(v) => update("past_medical_history.hospitalizations", linesToList(v, "reason"))}
          status={status.statusFor("past_medical_history.hospitalizations")}
        />
      </KVGrid>

      {/* ── Medications ────────────────────────────────────────────────── */}
      <SectionHeading>Medications</SectionHeading>
      {(record.medications || []).length === 0 ? (
        <p className={empty}>No medications documented</p>
      ) : (
        <div className="mb-2 flex flex-col gap-2">
          {(record.medications || []).map((m, i) => (
            <div
              key={i}
              className="grid grid-cols-[2fr_1fr_1fr_2fr] gap-2 rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-2"
            >
              <div>
                <FieldLabel>Drug</FieldLabel>
                <InlineField
                  value={m.name ?? ""}
                  onChange={(v) => updListField("medications", i, "name", v)}
                  status={m.name ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Dose</FieldLabel>
                <InlineField
                  value={m.dose ?? ""}
                  onChange={(v) => updListField("medications", i, "dose", v)}
                  status={m.dose ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Frequency</FieldLabel>
                <InlineField
                  value={m.frequency ?? ""}
                  onChange={(v) => updListField("medications", i, "frequency", v)}
                  status={m.frequency ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Indication</FieldLabel>
                <InlineField
                  value={m.indication ?? ""}
                  onChange={(v) => updListField("medications", i, "indication", v)}
                  status={m.indication ? "modified" : "normal"}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Family history ─────────────────────────────────────────────── */}
      <SectionHeading>Family History</SectionHeading>
      {(record.family_history || []).length === 0 ? (
        <p className={empty}>None documented</p>
      ) : (
        <div className="mb-2 flex flex-col gap-1.5">
          {(record.family_history || []).map((fh, i) => (
            <div
              key={i}
              className="grid grid-cols-[1fr_3fr] gap-2 rounded-md border border-zinc-200 bg-zinc-50/70 px-2.5 py-2"
            >
              <div>
                <FieldLabel>Member</FieldLabel>
                <InlineField
                  value={fh.member ?? ""}
                  onChange={(v) => updListField("family_history", i, "member", v)}
                  status={fh.member ? "modified" : "normal"}
                />
              </div>
              <div>
                <FieldLabel>Conditions</FieldLabel>
                <InlineField
                  value={(fh.conditions ?? []).join(", ")}
                  onChange={(v) =>
                    updListField(
                      "family_history",
                      i,
                      "conditions",
                      v
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                  placeholder="Comma-separated"
                  status={(fh.conditions ?? []).length > 0 ? "modified" : "normal"}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Social history ─────────────────────────────────────────────── */}
      <SectionHeading>Social History</SectionHeading>
      <KVGrid>
        {SOCIAL_KEYS.map((k) => (
          <Field
            key={k}
            label={titleCase(k)}
            value={record.social_history?.[k] ?? ""}
            onChange={(v) => update(`social_history.${k}`, v)}
            status={status.statusFor(`social_history.${k}`)}
            conflict={status.conflictMap.get(`social_history.${k}`)}
          />
        ))}
      </KVGrid>

      {/* ── ROS ────────────────────────────────────────────────────────── */}
      <SectionHeading>Review of Systems</SectionHeading>
      <KVGrid>
        {ROS_KEYS.map((k) => (
          <Field
            key={k}
            label={titleCase(k)}
            value={record.review_of_systems?.[k] ?? ""}
            onChange={(v) => update(`review_of_systems.${k}`, v)}
            placeholder="Not documented"
            status={status.statusFor(`review_of_systems.${k}`)}
            conflict={status.conflictMap.get(`review_of_systems.${k}`)}
          />
        ))}
      </KVGrid>

      {/* ── Vitals ─────────────────────────────────────────────────────── */}
      <SectionHeading>Vitals</SectionHeading>
      <KVGrid>
        {VITAL_KEYS.map(([k, label]) => (
          <Field
            key={k}
            label={label}
            value={record.vitals?.[k] ?? ""}
            onChange={(v) => update(`vitals.${k}`, v)}
            status={status.statusFor(`vitals.${k}`)}
            conflict={status.conflictMap.get(`vitals.${k}`)}
          />
        ))}
      </KVGrid>

      {/* ── Physical exam ──────────────────────────────────────────────── */}
      <SectionHeading>Physical Exam</SectionHeading>
      <KVGrid>
        {PE_KEYS.map((k) => (
          <Field
            key={k}
            label={titleCase(k)}
            value={record.physical_exam?.[k] ?? ""}
            onChange={(v) => update(`physical_exam.${k}`, v)}
            placeholder="Not documented"
            status={status.statusFor(`physical_exam.${k}`)}
            conflict={status.conflictMap.get(`physical_exam.${k}`)}
          />
        ))}
      </KVGrid>

      {/* ── Labs ───────────────────────────────────────────────────────── */}
      <SectionHeading>Laboratory Results</SectionHeading>
      {(record.labs || []).length === 0 ? (
        <p className={empty}>No lab results documented</p>
      ) : (
        <div className="mb-2 flex flex-col gap-2">
          {(record.labs || []).map((lab, i) => {
            const valueStatus: FieldStatus = lab.abnormal
              ? "conflict"
              : lab.value
              ? "modified"
              : "normal";
            return (
              <div
                key={i}
                className={cn(
                  "grid grid-cols-[3fr_2fr_1fr_2fr_2fr] gap-2 rounded-lg px-3 py-2",
                  lab.abnormal
                    ? "border border-rose-300 bg-rose-50/60"
                    : "border border-zinc-200 bg-zinc-50/70",
                )}
              >
                <div>
                  <FieldLabel>Test</FieldLabel>
                  <InlineField
                    value={lab.test ?? ""}
                    onChange={(v) => updListField("labs", i, "test", v)}
                    status={lab.test ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Value {lab.abnormal ? "⚠" : ""}</FieldLabel>
                  <input
                    value={lab.value ?? ""}
                    onChange={(e) => updListField("labs", i, "value", e.target.value)}
                    className={cn(
                      "w-full rounded-md border px-2.5 py-1.5 text-[12px] leading-relaxed outline-none focus:ring-2 focus:ring-foreground/15",
                      STATUS_CLASSES[valueStatus],
                      lab.abnormal && "font-semibold text-rose-700",
                    )}
                  />
                </div>
                <div>
                  <FieldLabel>Unit</FieldLabel>
                  <InlineField
                    value={lab.unit ?? ""}
                    onChange={(v) => updListField("labs", i, "unit", v)}
                    status={lab.unit ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Reference</FieldLabel>
                  <InlineField
                    value={lab.reference_range ?? ""}
                    onChange={(v) => updListField("labs", i, "reference_range", v)}
                    status={lab.reference_range ? "modified" : "normal"}
                  />
                </div>
                <div>
                  <FieldLabel>Date</FieldLabel>
                  <InlineField
                    value={lab.date ?? ""}
                    onChange={(v) => updListField("labs", i, "date", v)}
                    status={lab.date ? "modified" : "normal"}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Problem list & risk factors ────────────────────────────────── */}
      <SectionHeading>Problem List</SectionHeading>
      <Field
        multiline
        value={listToLines(record.problem_list, "name")}
        onChange={(v) => update("problem_list", linesToList(v, "name"))}
        placeholder="One problem per line"
        status={status.statusFor("problem_list")}
      />

      <SectionHeading>Risk Factors</SectionHeading>
      <Field
        multiline
        value={listToLines(record.risk_factors, "name")}
        onChange={(v) => update("risk_factors", linesToList(v, "name"))}
        placeholder="One risk factor per line"
        status={status.statusFor("risk_factors")}
      />

      {/* ── Assessment ─────────────────────────────────────────────────── */}
      <SectionHeading>Assessment</SectionHeading>
      <Field
        label="Clinical Reasoning"
        multiline
        value={record.assessment?.clinical_reasoning ?? ""}
        onChange={(v) => update("assessment.clinical_reasoning", v)}
        placeholder="Clinical reasoning…"
        status={status.statusFor("assessment.clinical_reasoning")}
      />
      <KVGrid>
        <Field
          label="Likely Diagnoses"
          multiline
          value={arrayJoin(record.assessment?.likely_diagnoses)}
          onChange={(v) => update("assessment.likely_diagnoses", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("assessment.likely_diagnoses")}
        />
        <Field
          label="Differential Diagnoses"
          multiline
          value={arrayJoin(record.assessment?.differential_diagnoses)}
          onChange={(v) => update("assessment.differential_diagnoses", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("assessment.differential_diagnoses")}
        />
      </KVGrid>

      {/* ── Plan ───────────────────────────────────────────────────────── */}
      <SectionHeading>Plan</SectionHeading>
      <KVGrid>
        <Field
          label="Medications Prescribed"
          multiline
          value={arrayJoin(record.plan?.medications_prescribed)}
          onChange={(v) => update("plan.medications_prescribed", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("plan.medications_prescribed")}
        />
        <Field
          label="Tests Ordered"
          multiline
          value={arrayJoin(record.plan?.tests_ordered)}
          onChange={(v) => update("plan.tests_ordered", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("plan.tests_ordered")}
        />
        <Field
          label="Lifestyle Recommendations"
          multiline
          value={arrayJoin(record.plan?.lifestyle_recommendations)}
          onChange={(v) => update("plan.lifestyle_recommendations", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("plan.lifestyle_recommendations")}
        />
        <Field
          label="Referrals"
          multiline
          value={arrayJoin(record.plan?.referrals)}
          onChange={(v) => update("plan.referrals", arraySplit(v))}
          placeholder="One per line"
          status={status.statusFor("plan.referrals")}
        />
      </KVGrid>
      <Field
        label="Follow-up"
        value={record.plan?.follow_up ?? ""}
        onChange={(v) => update("plan.follow_up", v)}
        status={status.statusFor("plan.follow_up")}
      />

      {/* ── Legend ─────────────────────────────────────────────────────── */}
      <div className="mt-6 flex flex-wrap gap-4 border-t border-foreground/10 pt-3">
        {[
          { cls: "bg-blue-50 border-blue-400", label: "Extracted / modified field" },
          { cls: "bg-yellow-50 border-yellow-400", label: "Uncertain (< 70% confidence)" },
          { cls: "bg-rose-50 border-rose-400", label: "Conflict — DB vs extracted" },
          { cls: "bg-rose-50/60 border-rose-300", label: "Abnormal lab value" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span className={cn("h-4 w-4 rounded-sm border", l.cls)} />
            <span className="font-mono text-[10px] text-foreground/55">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
