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

/**
 * PIPELINE_NODES — mirrors server/app/core/pipeline_progress.py::PIPELINE_NODE_DEFS.
 * At runtime the backend adds status, started_at, completed_at, duration_ms, and detail
 * fields to each object; this array is the static catalogue used for empty-state rendering.
 */
export const PIPELINE_NODES = [
  { name: "greeting",               label: "Initialising session",            phase: "ingestion",   description: "Loading session context and greeting" },
  { name: "load_patient_context",   label: "Loading patient history",         phase: "ingestion",   description: "Retrieving prior visits, medications, allergies from database" },
  { name: "ingest",                 label: "Ingesting transcript",            phase: "ingestion",   description: "Loading raw transcript segments into pipeline state" },
  { name: "clean_transcription",    label: "Cleaning transcription",          phase: "ingestion",   description: "Removing disfluencies, hesitations, and noise" },
  { name: "normalize_transcript",   label: "Normalising speaker labels",      phase: "ingestion",   description: "Standardising speaker labels and timestamps" },
  { name: "segment_and_chunk",      label: "Chunking into clinical segments", phase: "ingestion",   description: "Splitting conversation into topical clinical chunks" },
  { name: "extract_candidates",     label: "Extracting clinical entities",    phase: "extraction",  description: "NLP extraction of medications, diagnoses, vitals, ICD-10" },
  { name: "retrieve_evidence",      label: "Grounding evidence (pgvector)",   phase: "extraction",  description: "Anchoring each fact to its source utterance via semantic search" },
  { name: "fill_structured_record", label: "Compiling structured record",     phase: "extraction",  description: "Mapping extracted facts to the typed StructuredRecord schema" },
  { name: "clinical_suggestions",   label: "Checking drug interactions",      phase: "validation",  description: "Cross-checking allergies and drug-drug interactions" },
  { name: "validate_and_score",     label: "Validating & confidence scoring", phase: "validation",  description: "Pydantic validation, per-field confidence scoring, flag assignment" },
  { name: "repair",                 label: "Repairing schema errors",         phase: "validation",  description: "LLM-guided repair of schema validation failures (max 3 attempts)" },
  { name: "conflict_resolution",    label: "Resolving clinical conflicts",    phase: "validation",  description: "Resolving contradictions between new and historical facts" },
  { name: "human_review_gate",      label: "Awaiting physician review",       phase: "validation",  description: "Paused — physician sign-off required before write" },
  { name: "generate_note",          label: "Generating SOAP note",            phase: "output",      description: "LLM generating structured SOAP clinical note from record" },
  { name: "package_outputs",        label: "Packaging outputs",               phase: "output",      description: "Assembling final artifacts for storage and display" },
  { name: "persist_results",        label: "Persisting to database",          phase: "output",      description: "Writing record, embeddings, and audit trace to PostgreSQL" },
];

/** @deprecated Use PIPELINE_NODES instead — kept for any legacy component. */
export const PIPELINE_STEPS = PIPELINE_NODES.map((n) => n.label);

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
