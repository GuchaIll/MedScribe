import { apiFetch } from "./client";

export type RiskLevel = "low" | "moderate" | "high" | "critical";

export type AllergyAlert = {
  medication: string;
  allergen: string;
  severity?: string;
  detail?: string;
};

export type DrugInteraction = {
  drug_a: string;
  drug_b: string;
  severity?: string;
  detail?: string;
};

export type ClinicalSuggestions = {
  risk_level: RiskLevel;
  allergy_alerts: AllergyAlert[];
  drug_interactions: DrugInteraction[];
  recommendations?: string[];
  [k: string]: unknown;
};

export function getClinicalSuggestions(
  currentRecord: Record<string, unknown>,
  patientHistory: Record<string, unknown> | null = null,
): Promise<ClinicalSuggestions> {
  return apiFetch<ClinicalSuggestions>("/clinical/suggestions", {
    method: "POST",
    body: JSON.stringify({ current_record: currentRecord, patient_history: patientHistory }),
  });
}

export function checkAllergies(
  medications: Array<Record<string, unknown>>,
  allergies: Array<Record<string, unknown>>,
): Promise<{ allergy_alerts: AllergyAlert[]; risk_level: RiskLevel }> {
  return apiFetch("/clinical/check-allergies", {
    method: "POST",
    body: JSON.stringify({ medications, allergies }),
  });
}

export function checkInteractions(
  medications: Array<Record<string, unknown>>,
): Promise<{ drug_interactions: DrugInteraction[]; risk_level: RiskLevel }> {
  return apiFetch("/clinical/check-interactions", {
    method: "POST",
    body: JSON.stringify({ medications }),
  });
}
