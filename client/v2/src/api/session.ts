import { apiFetch } from "./client";
import type { StructuredRecord } from "@/lib/clinical";

/* ── Session lifecycle ─────────────────────────────────────────────────── */

export type SpeakerRoleSample = {
  role: "Clinician" | "Patient";
  status: string;
  file_name?: string;
  mime_type?: string;
  uploaded_at_ms?: number;
};

export type SpeakerRoleCheck = {
  session_id: string;
  required: boolean;
  status: "pending" | "collecting" | "ready_for_matching";
  method: "reference_voice_samples";
  expected_speakers: number;
  target_roles: Array<"Clinician" | "Patient">;
  instructions?: string[];
  samples?: SpeakerRoleSample[];
};

export type StartSessionResponse = {
  session_id: string;
  status?: string;
  message?: string;
  speaker_role_check?: SpeakerRoleCheck;
};
export type EndSessionResponse = { message: string };


export function startSession(): Promise<StartSessionResponse> {
  return apiFetch<StartSessionResponse>("/session/start", { method: "POST" });
}

export function endSession(sessionId: string): Promise<EndSessionResponse> {
  return apiFetch<EndSessionResponse>(`/session/${sessionId}/end`, { method: "POST" });
}

/* ── Live transcription ───────────────────────────────────────────────── */

export type Speaker = "Clinician" | "Patient" | "Unknown";

export type TranscribeResponse = {
  session_id: string;
  speaker: string;
  transcription: string;
  source: string;
  agent_message?: string | null;
};

export type UploadAudioSegmentInput = {
  segment_id: string;
  started_at_ms: number;
  ended_at_ms: number;
  sample_rate_hz?: number;
  mime_type?: string;
  optimistic_text?: string;
  optimistic_speaker?: Speaker;
  file: Blob;
  file_name?: string;
};

export type UploadAudioSegmentResponse = {
  session_id: string;
  segment_id: string;
  accepted: boolean;
  status: string;
  message?: string;
};

export function sendTranscription(
  sessionId: string,
  text: string,
  speaker: Speaker = "Unknown",
): Promise<TranscribeResponse> {
  return apiFetch<TranscribeResponse>(`/session/${sessionId}/transcribe`, {
    method: "POST",
    body: JSON.stringify({ text, speaker }),
  });
}

export function uploadAudioSegment(
  sessionId: string,
  input: UploadAudioSegmentInput,
): Promise<UploadAudioSegmentResponse> {
  const form = new FormData();
  form.set("segment_id", input.segment_id);
  form.set("started_at_ms", String(input.started_at_ms));
  form.set("ended_at_ms", String(input.ended_at_ms));
  if (input.sample_rate_hz) form.set("sample_rate_hz", String(input.sample_rate_hz));
  if (input.mime_type) form.set("mime_type", input.mime_type);
  if (input.optimistic_text) form.set("optimistic_text", input.optimistic_text);
  if (input.optimistic_speaker) form.set("optimistic_speaker", input.optimistic_speaker);
  form.set("file", input.file, input.file_name ?? `${input.segment_id}.wav`);

  return apiFetch<UploadAudioSegmentResponse>(`/session/${sessionId}/audio-segment`, {
    method: "POST",
    body: form,
    headers: {},
  });
}

/* ── Pipeline ─────────────────────────────────────────────────────────── */

export type Segment = {
  start: number;
  end: number;
  speaker: string;
  raw_text: string;
  confidence?: number;
};

export type RunPipelineResponse = {
  session_id: string;
  clinical_note?: string;
  structured_record?: Record<string, unknown>;
  clinical_suggestions?: Record<string, unknown>;
  validation_report?: Record<string, unknown>;
  message?: string;
};

export type TriggerPipelineResponse = {
  accepted: boolean;
  pipeline_id: string;
  message: string;
};

export function runPipeline(
  sessionId: string,
  patientId: string,
  doctorId: string,
  segments: Segment[],
): Promise<TriggerPipelineResponse> {
  return apiFetch<TriggerPipelineResponse>(`/session/${sessionId}/pipeline`, {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      patient_id: patientId,
      doctor_id: doctorId,
      segments,
    }),
  });
}

export type PipelineNodeStatus = "pending" | "running" | "completed" | "failed" | "skipped";
export type PipelinePhase = "ingestion" | "extraction" | "validation" | "output";

export type PipelineNodeProgress = {
  name: string;
  label: string;
  phase: PipelinePhase;
  description: string;
  status: PipelineNodeStatus;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  detail?: string | null;
};

export type PipelineProgress = {
  session_id: string;
  status: "idle" | "running" | "completed" | "failed";
  current_node?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  message?: string | null;
  clinical_note?: string | null;
  structured_record?: Record<string, unknown> | null;
  clinical_suggestions?: Record<string, unknown> | null;
  validation_report?: Record<string, unknown> | null;
  nodes: PipelineNodeProgress[];
};

export function getPipelineStatus(sessionId: string): Promise<PipelineProgress> {
  return apiFetch<PipelineProgress>(`/session/${sessionId}/pipeline/status`);
}

/* ── Live structured-record polling ───────────────────────────────────── */

export type SessionRecordResponse = {
  structured_record: StructuredRecord | null;
  last_updated: string | null;
};

export function getSessionRecord(sessionId: string): Promise<SessionRecordResponse> {
  return apiFetch<SessionRecordResponse>(`/session/${sessionId}/record`);
}

/* ── Assistant ────────────────────────────────────────────────────────── */

export type AssistantResponse = {
  answer: string;
  confidence: number;
  low_confidence: boolean;
  disclaimer?: string | null;
  sources?: Array<Record<string, unknown>>;
};

export function askAssistant(
  sessionId: string,
  patientId: string,
  question: string,
): Promise<AssistantResponse> {
  return apiFetch<AssistantResponse>(`/session/${sessionId}/assistant`, {
    method: "POST",
    body: JSON.stringify({ patient_id: patientId, question }),
  });
}
