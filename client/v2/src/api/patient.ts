import { apiFetch } from "./client";

export type PatientProfile = {
  patient_id: string;
  demographics?: Record<string, unknown>;
  medications?: Array<Record<string, unknown>>;
  allergies?: Array<Record<string, unknown>>;
  past_medical_history?: Record<string, unknown>;
  vitals?: Record<string, unknown>;
  [k: string]: unknown;
};

/** Patient's longitudinal medical profile (historical data from DB). */
export function getPatientProfile(patientId: string): Promise<PatientProfile> {
  return apiFetch<PatientProfile>(`/patient/${patientId}/profile`);
}
