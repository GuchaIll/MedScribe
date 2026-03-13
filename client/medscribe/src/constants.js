/* ─── Shared Constants ────────────────────────────────────────────────────── */

export const PHYSICIAN = {
  name: "Physician",
  role: "Physician",
  avatar:
    "https://lh3.googleusercontent.com/aida-public/AB6AXuB3qjaS1C0vJOCr4P_V3D2rtvbzcDmPp4IGcDJBbiaWY5Jc8cQLv_7SloUmXjGERZHoBZ3ue3TUruz-fpizwNp_RjrHoTAkXCoLgG7_2lJ8OxLDgdpRcJvIcxfzrPK8f52huiiuzCAJW_zOOtyWrlsqjuKJkAm57f5FTnn68gcOMl2pIDLThoV4jH8GeANoOzFzcM2k29jr3EApUp_xq3tOfA-U15tX6snqMMhUXQAK3Y-Nqh4CPkeep4wVVxORhLQLnZOY886zO8s",
};

export const PATIENT = {
  name: "Patient",
  role: "Patient",
  avatar:
    "https://lh3.googleusercontent.com/aida-public/AB6AXuBZtFUNNn8LHg3tOdc4e7urFJvEig1aDiAlvExh5rZXF1GfQj7vrShPeijefXRCCQE8u9f7ipIzXJUC7SHiteVIxAM9M8sG0tnSJdc2hjQ4TaDZy6A4vygstThkIiBjv0Mwb44rAcQv-DvfwkDgx9nxkXceMlJu6pNLJuEVWyht5FPOCsMGs3zmN7KRJeMtLpcTs4TEh3AKSliIWCO9xEi8mpz92Ga2jjrsGD4vwaX6afjyhRT6LcfcBgyBtfiM8_unGVCZZmQVxjw",
};

export const AGENT = {
  name: "MedScribe Agent",
  role: "Agent",
  avatar: null, // rendered as icon
};

/* ── Record field change status colors ── */
export const CHANGE_COLORS = {
  added: {
    bg: "rgba(34,197,94,0.10)",
    border: "rgba(34,197,94,0.30)",
    dot: "#22c55e",
    label: "Updated",
  },
  ok: {
    bg: "rgba(34,197,94,0.08)",
    border: "rgba(34,197,94,0.22)",
    dot: "#22c55e",
    label: "Verified",
  },
  warning: {
    bg: "rgba(234,179,8,0.10)",
    border: "rgba(234,179,8,0.30)",
    dot: "#eab308",
    label: "Uncertain",
  },
  conflict: {
    bg: "rgba(239,68,68,0.10)",
    border: "rgba(239,68,68,0.30)",
    dot: "#ef4444",
    label: "Conflict",
  },
  unchanged: {
    bg: "transparent",
    border: "rgba(0,0,0,0.06)",
    dot: "#d4d4d8",
    label: "Unchanged",
  },
};

export const PIPELINE_STEPS = [
  "Detecting speaker…",
  "Analyzing speech patterns…",
  "Extracting medical entities…",
  "Checking medication database…",
  "Tagging ICD-10 codes…",
  "Updating patient record…",
];

export const DOC_TABS = [
  "Session Summary",
  "Discharge Note",
  "Uploaded Docs",
  "Medical Record",
];

/* ─── Placeholder patient info (replaced by API data when pipeline completes) */
export const EMPTY_DOCUMENTS = {
  "Session Summary": { generated: null, badge: null, sections: [] },
  "Discharge Note": { generated: null, badge: null, sections: [] },
  "Uploaded Docs": { generated: null, badge: null, files: [] },
  "Medical Record": { generated: null, badge: null, sections: [] },
};
