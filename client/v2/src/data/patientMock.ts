/**
 * All mock clinical data lives here. When the real backend wires up
 * (`services/`, `server/`, MedScribe pipeline), replace these constants with
 * React Query hooks against the gateway and delete this file.
 */

export type Med = { name: string; sub: string; status: string; statusTone: "emerald" | "amber" | "rose" };
export type Allergy = { name: string; severity: "Mild" | "Moderate" | "Severe" };
export type LabRow = { test: string; value: string; unit: string; ref: string; date: string };

export const tabs = [
  "Overview",
  "Patient profile",
  "BGL Analysis",
  "Medications",
  "Lab results",
  "Mini Goals",
];

export const timeline = [
  { date: "Dec 2022", title: "Pre-diabetic", a1c: "10.4" },
  { date: "JAN 2022", title: "Type 2", a1c: "10.4" },
  { date: "JUL 2021", title: "Chronic thyroid disorder", a1c: "10.4" },
  { date: "JUL 2021", title: "Angina Pectoris", a1c: "10.4" },
  { date: "JUL", title: "Stroke", a1c: "" },
];

export const initialMedications: Med[] = [
  { name: "ACTRAPID ® HM 1", sub: "Amaryl 1 mg", status: "Adherent", statusTone: "emerald" },
  { name: "Panadol 1000m", sub: "Vitacid 1000m", status: "Somehow adherent", statusTone: "amber" },
  { name: "Amaryl 1 mg", sub: "Amaryl 1 mg", status: "Not adherent", statusTone: "rose" },
  { name: "Vitacid 1000m", sub: "Vitacid 1000m", status: "Adherent", statusTone: "emerald" },
];

export const initialAllergies: Allergy[] = [
  { name: "Penicillin", severity: "Severe" },
  { name: "Peanuts", severity: "Moderate" },
  { name: "Latex", severity: "Mild" },
];

export const initialLabs: LabRow[] = [
  { test: "HbA1c", value: "7.8", unit: "%", ref: "<6.5", date: "Apr 2026" },
  { test: "Fasting glucose", value: "142", unit: "mg/dL", ref: "70–99", date: "Apr 2026" },
  { test: "LDL", value: "118", unit: "mg/dL", ref: "<100", date: "Mar 2026" },
  { test: "HDL", value: "44", unit: "mg/dL", ref: ">40", date: "Mar 2026" },
  { test: "Triglycerides", value: "168", unit: "mg/dL", ref: "<150", date: "Mar 2026" },
];

export const labTrends: Record<string, { m: string; v: number }[]> = {
  HbA1c: [
    { m: "Oct", v: 9.1 }, { m: "Nov", v: 8.7 }, { m: "Dec", v: 8.4 },
    { m: "Jan", v: 8.2 }, { m: "Feb", v: 8.0 }, { m: "Mar", v: 7.9 }, { m: "Apr", v: 7.8 },
  ],
  Glucose: [
    { m: "Oct", v: 178 }, { m: "Nov", v: 170 }, { m: "Dec", v: 162 },
    { m: "Jan", v: 155 }, { m: "Feb", v: 150 }, { m: "Mar", v: 146 }, { m: "Apr", v: 142 },
  ],
  Lipids: [
    { m: "Oct", v: 145 }, { m: "Nov", v: 138 }, { m: "Dec", v: 132 },
    { m: "Jan", v: 128 }, { m: "Feb", v: 124 }, { m: "Mar", v: 120 }, { m: "Apr", v: 118 },
  ],
};

export const adherenceWeeks: number[][] = [
  [1, 1, 1, 1, 0, 1, 1],
  [1, 0, 1, 1, 1, 1, 0],
  [1, 1, 1, 0, 1, 1, 1],
  [1, 1, 1, 1, 1, 1, 1],
];
