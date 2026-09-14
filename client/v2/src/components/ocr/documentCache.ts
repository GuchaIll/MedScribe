/**
 * In-memory cache for uploaded-document metadata shared between
 * `UploadModal` (writer) and `DocumentReview` (reader).
 *
 * Survives client-side navigation; lost on page reload, in which case
 * DocumentReview falls back to /api/session/:id/record. Keyed by the file's
 * original_name (the same string we URL-encode into the route).
 */
import type { UploadedFileMeta } from "@/api";
import type { FieldChange, StructuredRecord } from "@/lib/clinical";

export type DocumentReviewStatus =
  | "Pending"
  | "Processing"
  | "Processed"
  | "Conflicts"
  | "Failed";

export type CachedDocument = {
  /** original_name from the backend; mirrors the URL param. */
  filename: string;
  content_type?: string;
  size?: number;
  /** Client-generated blob URL pointing at the original File. */
  previewUrl?: string;
  document_type?: string;
  overall_confidence?: number;
  fields_extracted?: number;
  conflicts_detected?: number;
  field_changes?: FieldChange[];
  conflict_details?: Array<Record<string, unknown>>;
  agent_summary?: string;
  processing_errors?: string[];
  /** Per-file structured record built from this upload's OCR fields. */
  structured_record?: StructuredRecord | null;
  status: DocumentReviewStatus;
  error?: string;
};

const store = new Map<string, CachedDocument>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

const deriveStatus = (meta: UploadedFileMeta): DocumentReviewStatus => {
  const normalized = (meta.status || "").toLowerCase();
  if (normalized === "pending_ocr" || normalized === "pending") return "Pending";
  if (normalized === "processing") return "Processing";
  if (normalized === "processed") return "Processed";
  if (normalized === "conflicts") return "Conflicts";
  if (normalized === "failed") return "Failed";
  if (meta.error) return "Failed";
  if (meta.processing_errors && meta.processing_errors.length > 0) return "Failed";
  if ((meta.conflicts_detected ?? 0) > 0) return "Conflicts";
  if ((meta.fields_extracted ?? 0) === 0) return "Processing";
  return "Processed";
};

export type CacheInput = {
  meta: UploadedFileMeta;
  /** Blob URL for the original File (preview only). */
  previewUrl?: string;
  /** Session-level merged record returned alongside the upload. */
  structured_record?: StructuredRecord | null;
};

export const cacheDocument = ({
  meta,
  previewUrl,
  structured_record,
}: CacheInput): CachedDocument => {
  const entry: CachedDocument = {
    filename: meta.original_name,
    content_type: meta.content_type,
    size: meta.size,
    previewUrl,
    document_type: meta.document_type,
    overall_confidence: meta.overall_confidence,
    fields_extracted: meta.fields_extracted,
    conflicts_detected: meta.conflicts_detected,
    field_changes: meta.field_changes as FieldChange[] | undefined,
    conflict_details: meta.conflict_details,
    agent_summary: meta.agent_summary,
    processing_errors: meta.processing_errors,
    structured_record: structured_record ?? null,
    status: deriveStatus(meta),
    error: meta.error,
  };
  store.set(entry.filename, entry);
  emit();
  return entry;
};

export const cacheDocuments = (inputs: CacheInput[]): CachedDocument[] =>
  inputs.map(cacheDocument);

export const getCachedDocument = (filename: string): CachedDocument | undefined =>
  store.get(filename);

/** Subscribe to cache changes — used by DocumentReview to react to late OCR finishes. */
export const subscribeDocumentCache = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const clearDocumentCache = () => {
  store.forEach((entry) => {
    if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
  });
  store.clear();
  emit();
};
