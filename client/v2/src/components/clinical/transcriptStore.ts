import { useSyncExternalStore } from "react";
import type { ReviewField } from "@/lib/pipelineReview";

export type Attachment = {
  name: string;
  type: string;
  size: number;
  url: string;
};

/**
 * A "review this" handoff attached to a Scribe bubble after OCR completes.
 * Renders as a card with the top extracted field changes inline and a square
 * action button that opens the OCR comparison panel.
 */
export type ReviewRequest = {
  filename: string;
  /** SPA route — clicking the square button navigates here. */
  reviewUrl: string;
  documentType?: string;
  fieldsCount?: number;
  conflictsCount?: number;
  /** Up to N field-change rows to preview inline. */
  fieldChanges?: Array<{ field_name: string; value: unknown; status?: "modified" | "lowConf" | "conflict" }>;
};

/**
 * Post-pipeline change-review payload. Attached to a Scribe bubble when the
 * LangGraph run finishes with validation_report.needs_review === true.
 */
export type ReviewChanges = {
  fields: ReviewField[];
  approved?: boolean;
};

export type Turn = {
  id: string;
  speaker: "Clinician" | "Patient" | "Scribe";
  time: string;
  text: string;
  partial?: boolean;
  attachment?: Attachment;
  reviewRequest?: ReviewRequest;
  reviewChanges?: ReviewChanges;
  kind?: "message" | "document" | "summary" | "soap" | "review_request" | "review_changes";
};

const initialTurns: Turn[] = [
  {
    id: "t1",
    speaker: "Clinician",
    time: "10:02",
    text: "Good morning. Can you walk me through what brought you in today?",
  },
  {
    id: "t2",
    speaker: "Patient",
    time: "10:02",
    text: "I've had this dull pressure in my chest for about three days, mostly when I climb stairs.",
  },
  {
    id: "t3",
    speaker: "Scribe",
    time: "10:03",
    text: "Chief complaint: exertional chest pressure × 3 days. No radiation reported. Captured for SOAP note.",
  },
  {
    id: "t4",
    speaker: "Clinician",
    time: "10:04",
    text: "Any shortness of breath, sweating, or nausea with it?",
  },
  {
    id: "t5",
    speaker: "Patient",
    time: "10:05",
    text: "A little out of breath. No sweating. Maybe mild nausea once.",
    partial: true,
  },
];

let turns: Turn[] = [...initialTurns];
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((l) => l());

const nowTime = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

export const transcriptStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return turns;
  },
  addTurn(turn: Omit<Turn, "id" | "time"> & { time?: string; id?: string }) {
    const t: Turn = {
      id: turn.id ?? `t${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      time: turn.time ?? nowTime(),
      ...turn,
    } as Turn;
    turns = [...turns, t];
    emit();
    return t;
  },
  updateTurn(id: string, text: string) {
    turns = turns.map((t) => (t.id === id ? { ...t, text } : t));
    emit();
  },
  patchTurn(id: string, patch: Partial<Omit<Turn, "id">>) {
    turns = turns.map((t) => (t.id === id ? { ...t, ...patch } : t));
    emit();
  },
};

export const useTranscriptTurns = () =>
  useSyncExternalStore(transcriptStore.subscribe, transcriptStore.getSnapshot, transcriptStore.getSnapshot);
