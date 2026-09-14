/**
 * Static catalogue of the 16 LangGraph pipeline nodes.
 *
 * Mirrors server/app/core/pipeline_progress.py::PIPELINE_NODE_DEFS, which in
 * turn mirrors the nodes registered in server/app/agents/graph.py (the single
 * source of truth). Names MUST stay identical across all three. At runtime the
 * backend overlays status / started_at / completed_at / duration_ms / detail
 * on top of these definitions; PipelineProgress merges the two views.
 */
import type { PipelineNodeProgress, PipelinePhase } from "@/api";

export type PipelineNodeDef = {
  name: string;
  label: string;
  phase: PipelinePhase;
  description: string;
};

export const PIPELINE_NODES: readonly PipelineNodeDef[] = [
  { name: "greeting",               label: "Initialising session",            phase: "ingestion",  description: "Loading session context and greeting" },
  { name: "load_patient_context",   label: "Loading patient history",         phase: "ingestion",  description: "Retrieving prior visits, medications, allergies from database" },
  { name: "preprocess",             label: "Preprocessing transcript",        phase: "ingestion",  description: "Ingesting, normalising speaker labels, and chunking into clinical segments" },
  { name: "clean_transcription",    label: "Cleaning transcription",          phase: "ingestion",  description: "Removing disfluencies, hesitations, and noise" },
  { name: "extract_candidates",       label: "Extracting clinical entities",    phase: "extraction", description: "NLP extraction of medications, diagnoses, vitals, ICD-10" },
  { name: "run_diagnostic_reasoning", label: "Diagnostic reasoning",            phase: "extraction", description: "LLM differential diagnosis over extracted candidates" },
  { name: "retrieve_evidence",      label: "Grounding evidence (pgvector)",   phase: "extraction", description: "Anchoring each fact to its source utterance via semantic search" },
  { name: "fill_structured_record", label: "Compiling structured record",     phase: "extraction", description: "Mapping extracted facts to the typed StructuredRecord schema" },
  { name: "run_clinical_suggestions", label: "Checking drug interactions",    phase: "validation", description: "Cross-checking allergies and drug-drug interactions" },
  { name: "validate_and_score",     label: "Validating & confidence scoring", phase: "validation", description: "Pydantic validation, per-field confidence scoring, flag assignment" },
  { name: "repair",                 label: "Repairing schema errors",         phase: "validation", description: "LLM-guided repair of schema validation failures (max 3 attempts)" },
  { name: "conflict_resolution",    label: "Resolving clinical conflicts",    phase: "validation", description: "Resolving contradictions between new and historical facts" },
  { name: "human_review_gate",      label: "Awaiting physician review",       phase: "validation", description: "Paused — physician sign-off required before write" },
  { name: "generate_note",          label: "Generating SOAP note",            phase: "output",     description: "LLM generating structured SOAP clinical note from record" },
  { name: "package_outputs",        label: "Packaging outputs",               phase: "output",     description: "Assembling final artifacts for storage and display" },
  { name: "persist_results",        label: "Persisting to database",          phase: "output",     description: "Writing record, embeddings, and audit trace to PostgreSQL" },
];

export const PHASES: readonly PipelinePhase[] = ["ingestion", "extraction", "validation", "output"];

export const PHASE_LABELS: Record<PipelinePhase, string> = {
  ingestion: "Ingestion",
  extraction: "Extraction",
  validation: "Validation",
  output: "Output",
};

/**
 * Overlay live node progress on top of the static catalogue. Any node the
 * backend hasn't started yet falls back to status "pending".
 */
export const mergeNodeStatus = (
  live: PipelineNodeProgress[] | undefined | null,
): PipelineNodeProgress[] => {
  const byName = new Map<string, PipelineNodeProgress>();
  (live ?? []).forEach((n) => byName.set(n.name, n));
  return PIPELINE_NODES.map((def) => {
    const known = byName.get(def.name);
    if (known) return known;
    return {
      ...def,
      status: "pending",
    };
  });
};
