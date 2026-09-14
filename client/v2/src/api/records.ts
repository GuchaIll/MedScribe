import { apiRawFetch, ApiError } from "./client";

export type RecordTemplate = "soap" | "discharge" | "consultation" | "progress";
export type RecordFormat = "html" | "pdf" | "text";

export type RecordTemplateMeta = {
  name: string;
  description?: string;
  formats: RecordFormat[];
};

export async function getTemplates(): Promise<RecordTemplateMeta[]> {
  const res = await apiRawFetch("/records/templates");
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  return res.json();
}

/**
 * Render a clinical document. Returns a string for html/text and a Blob for pdf.
 */
export async function generateRecord(
  record: Record<string, unknown>,
  template: RecordTemplate = "soap",
  format: RecordFormat = "html",
  clinicalSuggestions: Record<string, unknown> | null = null,
): Promise<string | Blob> {
  const res = await apiRawFetch("/records/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ record, template, format, clinical_suggestions: clinicalSuggestions }),
  });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  if (format === "pdf") return res.blob();
  return res.text();
}

export async function previewRecord(
  record: Record<string, unknown>,
  template: RecordTemplate = "soap",
): Promise<string> {
  const res = await apiRawFetch("/records/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ record, template, format: "html" }),
  });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  return res.text();
}
