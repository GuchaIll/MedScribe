import { apiRawFetch } from "./client";
import type { StructuredRecord } from "@/lib/clinical";

/** Local metadata + a reference to the raw File for later upload. */
export type UploadItem = {
  name: string;
  size: number;
  type: string;
  lastModified: number;
  file: File;
};

export function prepareUpload(file: File): UploadItem {
  return {
    name: file.name,
    size: file.size,
    type: file.type,
    lastModified: file.lastModified,
    file,
  };
}

/**
 * Per-file metadata returned by POST /api/session/{id}/upload.
 *
 * Phase 2 gateway uploads are async: the request captures the original file,
 * queues OCR, and returns pending document metadata immediately.
 */
export type UploadedFileMeta = {
  document_id: string;
  original_name: string;
  stored_name?: string;
  size?: number;
  content_type?: string;
  path?: string;
  document_type?: string;
  classification_confidence?: number;
  overall_confidence?: number;
  fields_extracted?: number;
  conflicts_detected?: number;
  queue_items_created?: number;
  processing_errors?: string[];
  field_changes?: Array<{ field_name: string; value: unknown }>;
  conflict_details?: Array<Record<string, unknown>>;
  agent_summary?: string;
  structured_record?: StructuredRecord | null;
  status?: string;
  /** Only present when the upload failed at the OCR stage. */
  error?: string;
};

export type UploadResponse = {
  session_id: string;
  uploaded: number;
  files: UploadedFileMeta[];
  /** Session-level merged record after the new OCR fields were folded in. */
  structured_record?: StructuredRecord | null;
};

export async function uploadDocuments(
  sessionId: string,
  uploadItems: UploadItem[],
): Promise<UploadResponse> {
  const files = await Promise.all(
    uploadItems.map(async (item): Promise<UploadedFileMeta> => {
      const form = new FormData();
      form.append("file", item.file, item.name);

      const res = await apiRawFetch(`/session/${sessionId}/upload`, {
        method: "POST",
        body: form,
        // do NOT set Content-Type — browser sets multipart boundary automatically
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`Upload failed (${res.status}): ${body}`);
      }

      const payload = (await res.json()) as {
        document_id: string;
        original_name: string;
        path: string;
        content_type: string;
        status?: string;
      };

      return {
        document_id: payload.document_id,
        original_name: payload.original_name,
        content_type: payload.content_type || item.type,
        size: item.size,
        path: payload.path,
        document_type: "pending_ocr",
        overall_confidence: 0,
        fields_extracted: 0,
        conflicts_detected: 0,
        processing_errors: [],
        status: payload.status ?? "pending_ocr",
        agent_summary: "Queued for OCR extraction. Review will be available after background processing completes.",
      };
    }),
  );

  return {
    session_id: sessionId,
    uploaded: files.length,
    files,
    structured_record: null,
  };
}

export type SessionDocumentsResponse = {
  documents: UploadedFileMeta[];
};

export async function getSessionDocuments(sessionId: string): Promise<SessionDocumentsResponse> {
  const res = await apiRawFetch(`/session/${sessionId}/documents`, {
    method: "GET",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Documents fetch failed (${res.status}): ${body}`);
  }
  return res.json();
}
