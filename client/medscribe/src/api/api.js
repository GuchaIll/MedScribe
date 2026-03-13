/**
 * API client for the MedicalTranscription backend.
 * CRA proxy forwards /api/* → backend (see package.json "proxy").
 */

const BASE = '/api';

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

// ── Session ─────────────────────────────────────────────────────────────────

/** Start a new transcription session → { session_id, message } */
export async function startSession() {
  return apiFetch('/session/start', { method: 'POST' });
}

/** End an active session → { message } */
export async function endSession(sessionId) {
  return apiFetch(`/session/${sessionId}/end`, { method: 'POST' });
}

/**
 * Send a single utterance for live transcription.
 * → { session_id, speaker, transcription, source, agent_message }
 */
export async function sendTranscription(sessionId, text, speaker = 'Unknown') {
  return apiFetch(`/session/${sessionId}/transcribe`, {
    method: 'POST',
    body: JSON.stringify({ text, speaker }),
  });
}

// ── Pipeline ────────────────────────────────────────────────────────────────

/**
 * Run the full 17-node LangGraph pipeline.
 * segments: [{ start, end, speaker, raw_text, confidence? }]
 * → { session_id, clinical_note, structured_record, clinical_suggestions, validation_report, message }
 */
export async function runPipeline(sessionId, patientId, doctorId, segments) {
  return apiFetch(`/session/${sessionId}/pipeline`, {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      patient_id: patientId,
      doctor_id: doctorId,
      segments,
    }),
  });
}

// ── Transcript ──────────────────────────────────────────────────────────────

/**
 * LLM speaker reclassification.
 * messages: [{ id, speaker, content, timestamp, type }]
 * → { messages: [...] } with updated speaker labels
 */
export async function reclassifyTranscript(messages) {
  const res = await apiFetch('/transcript/reclassify', {
    method: 'POST',
    body: JSON.stringify({ messages }),
  });
  return res.messages;
}

// ── Records ─────────────────────────────────────────────────────────────────

/** Get available templates → [{ name, description, formats }] */
export async function getTemplates() {
  return apiFetch('/records/templates');
}

/**
 * Generate a clinical document.
 * format: 'html' | 'pdf' | 'text'
 * template: 'soap' | 'discharge' | 'consultation' | 'progress'
 */
export async function generateRecord(record, template = 'soap', format = 'html', clinicalSuggestions = null) {
  const res = await fetch(`${BASE}/records/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      record,
      template,
      format,
      clinical_suggestions: clinicalSuggestions,
    }),
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  if (format === 'pdf') return res.blob();
  return res.text();
}

/** Preview a record (always HTML) */
export async function previewRecord(record, template = 'soap') {
  const res = await fetch(`${BASE}/records/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record, template, format: 'html' }),
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.text();
}

// ── Clinical ────────────────────────────────────────────────────────────────

/** Full clinical decision support → { risk_level, allergy_alerts, drug_interactions, … } */
export async function getClinicalSuggestions(currentRecord, patientHistory = null) {
  return apiFetch('/clinical/suggestions', {
    method: 'POST',
    body: JSON.stringify({
      current_record: currentRecord,
      patient_history: patientHistory,
    }),
  });
}

/** Quick allergy check → { allergy_alerts, risk_level } */
export async function checkAllergies(medications, allergies) {
  return apiFetch('/clinical/check-allergies', {
    method: 'POST',
    body: JSON.stringify({ medications, allergies }),
  });
}

/** Quick drug-interaction check → { drug_interactions, risk_level } */
export async function checkInteractions(medications) {
  return apiFetch('/clinical/check-interactions', {
    method: 'POST',
    body: JSON.stringify({ medications }),
  });
}

// ── TTS ─────────────────────────────────────────────────────────────────────

let _currentAudio = null;

/** Speak text via ElevenLabs TTS, falling back to browser SpeechSynthesis */
export async function speakText(text) {
  if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }
  try {
    const res = await fetch(`${BASE}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      _currentAudio = new Audio(url);
      _currentAudio.onended = () => { URL.revokeObjectURL(url); _currentAudio = null; };
      await _currentAudio.play();
      return;
    }
  } catch { /* fall through */ }
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.9;
    window.speechSynthesis.speak(u);
  }
}

// ── Assistant ────────────────────────────────────────────────────────────────

/**
 * Ask the medical assistant a question grounded in the patient's records.
 * Triggered when the doctor says "Assistant, <question>" during a session.
 *
 * @param {string} sessionId
 * @param {string} patientId
 * @param {string} question  - The extracted question (after "Assistant,")
 * @returns {Promise<{answer, confidence, low_confidence, disclaimer, sources}>}
 */
export async function askAssistant(sessionId, patientId, question) {
  return apiFetch(`/session/${sessionId}/assistant`, {
    method: 'POST',
    body: JSON.stringify({ patient_id: patientId, question }),
  });
}

// ── Upload ──────────────────────────────────────────────────────────────────

/**
 * Prepare a file for display in the upload panel (metadata only).
 * We keep the raw File object in `.file` so it can be sent later.
 */
export function prepareUpload(file) {
  return {
    name: file.name,
    size: file.size,
    type: file.type,
    lastModified: file.lastModified,
    file, // keep the actual File blob for upload
  };
}

/**
 * Upload files to the backend, trigger OCR pipeline, and return results
 * including extracted fields, conflicts, and an agent summary.
 *
 * @param {string} sessionId
 * @param {Array<{file: File}>} uploadItems - items from prepareUpload()
 * @returns {Promise<Object>} - { session_id, uploaded, files: [...] }
 */
export async function uploadDocuments(sessionId, uploadItems) {
  const form = new FormData();
  for (const item of uploadItems) {
    form.append("files", item.file, item.name);
  }
  const res = await fetch(`${BASE}/session/${sessionId}/upload`, {
    method: "POST",
    body: form,
    // Do NOT set Content-Type — browser sets multipart boundary automatically
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Upload failed (${res.status}): ${body}`);
  }
  return res.json();
}
