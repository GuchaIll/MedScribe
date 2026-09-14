import { apiFetch } from "./client";

export type LLMProvider = {
  name: string;
  display_name?: string;
  available: boolean;
  model?: string;
  description?: string;
};

export type LLMProvidersResponse = {
  providers: LLMProvider[];
  selected?: string | null;
};

export type LLMStatusResponse = {
  provider: string | null;
  model: string | null;
  ready: boolean;
};

export function getLLMProviders(): Promise<LLMProvidersResponse> {
  return apiFetch<LLMProvidersResponse>("/llm/providers");
}

export function getLLMStatus(): Promise<LLMStatusResponse> {
  return apiFetch<LLMStatusResponse>("/llm/status");
}

export function selectLLMProvider(providerName: string): Promise<{ message: string }> {
  return apiFetch<{ message: string }>("/llm/provider/select", {
    method: "POST",
    body: JSON.stringify({ provider_name: providerName }),
  });
}
