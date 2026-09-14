import { useRef, useState } from "react";
import { Loader2, Plus, Upload, X } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useSession } from "@/hooks/useSession";
import {
  getSessionDocuments,
  prepareUpload,
  uploadDocuments,
  type UploadItem,
} from "@/api";
import { transcriptStore } from "@/components/clinical/transcriptStore";
import type { StructuredRecord } from "@/lib/clinical";
import { cacheDocument, type CachedDocument } from "./documentCache";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff,.dicom,.dcm";

type UploadModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Fired once upload requests have been accepted. OCR may still be running in
   * the background; callers should treat returned cache entries as pending
   * until a processed/conflict status arrives.
   */
  onUploaded?: (entries: CachedDocument[]) => void;
};

const fmtKb = (bytes: number) => `${(bytes / 1024).toFixed(1)} kb`;

/** "Document ready for review: foo.pdf · lab_report · 12 fields · 2 conflicts" */
const summarizeForReview = (succeeded: CachedDocument[]): string => {
  if (succeeded.length !== 1) return `${succeeded.length} documents ready for review`;
  const f = succeeded[0];
  const parts: string[] = [`Document ready for review: ${f.filename}`];
  if (f.document_type) parts.push(`type: ${f.document_type}`);
  if (typeof f.fields_extracted === "number") {
    parts.push(`${f.fields_extracted} field${f.fields_extracted === 1 ? "" : "s"}`);
  }
  if (typeof f.conflicts_detected === "number" && f.conflicts_detected > 0) {
    parts.push(`${f.conflicts_detected} conflict${f.conflicts_detected === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
};

const summarizeQueued = (queued: CachedDocument[]): string => {
  if (queued.length !== 1) return `${queued.length} documents queued for OCR extraction`;
  return `Document queued for OCR extraction: ${queued[0].filename}`;
};

const isReviewableStatus = (status: CachedDocument["status"]) =>
  status === "Processed" || status === "Conflicts";

const postReviewReady = (entry: CachedDocument) => {
  transcriptStore.addTurn({
    speaker: "Scribe",
    text:
      entry.agent_summary ??
      "Open the compare view to approve, override, or reject extracted fields.",
    kind: "review_request",
    reviewRequest: toReviewRequest(entry),
  });
};

/** Build blob: URLs for each upload item. Skips files that can't be previewed. */
const buildPreviewUrls = (items: UploadItem[]): Map<string, string> => {
  const map = new Map<string, string>();
  items.forEach((item) => {
    try {
      map.set(item.name, URL.createObjectURL(item.file));
    } catch {
      /* createObjectURL can fail on some browsers for huge files; skip preview. */
    }
  });
  return map;
};

const revokeAll = (urls: Iterable<string>) => {
  for (const url of urls) URL.revokeObjectURL(url);
};

/**
 * Build the ReviewRequest payload attached to the Scribe handoff bubble.
 * Marks each field change as "conflict" when its name appears in
 * conflict_details, otherwise as "modified" (extracted).
 */
const toReviewRequest = (entry: CachedDocument) => {
  const conflictFields = new Set(
    (entry.conflict_details ?? [])
      .map((c) => (typeof c.field === "string" ? c.field : null))
      .filter((f): f is string => !!f),
  );

  const fieldChanges = (entry.field_changes ?? []).map((fc) => ({
    field_name: fc.field_name,
    value: fc.value,
    status: conflictFields.has(fc.field_name)
      ? ("conflict" as const)
      : ("modified" as const),
  }));

  return {
    filename: entry.filename,
    reviewUrl: `/document/${encodeURIComponent(entry.filename)}`,
    documentType: entry.document_type,
    fieldsCount: entry.fields_extracted ?? fieldChanges.length,
    conflictsCount: entry.conflicts_detected ?? conflictFields.size,
    fieldChanges,
  };
};

/**
 * After upload returns, either:
 *   - replace the placeholder with a queued-processing message (async OCR), or
 *   - replace it with a review-handoff bubble when processed data is already available, or
 *   - replace it with an error line (every file failed).
 *
 * Processed uploads emit one Scribe bubble per file. The bubble's body is the
 * agent summary; the attached ReviewRequest renders the field-changes preview
 * and the square Open-compare-view button.
 */
const announceReview = (
  placeholderId: string,
  entries: CachedDocument[],
): { succeeded: CachedDocument[]; queued: CachedDocument[]; failed: string[] } => {
  const succeeded = entries.filter((e) => e.status === "Processed" || e.status === "Conflicts");
  const queued = entries.filter((e) => e.status === "Pending" || e.status === "Processing");
  const failed = entries.filter((e) => e.status === "Failed").map((e) => e.filename);

  if (succeeded.length === 0 && queued.length === 0) {
    transcriptStore.updateTurn(
      placeholderId,
      `Upload failed — ${failed.join(", ") || "OCR pipeline error"}`,
    );
    return { succeeded, queued, failed };
  }

  if (succeeded.length === 0 && queued.length > 0) {
    transcriptStore.updateTurn(placeholderId, summarizeQueued(queued));
    for (const entry of queued) {
      transcriptStore.addTurn({
        speaker: "Scribe",
        text:
          entry.agent_summary ??
          "OCR extraction is running in the background. This document will become reviewable when processing completes.",
        kind: "message",
      });
    }
    return { succeeded, queued, failed };
  }

  transcriptStore.updateTurn(placeholderId, summarizeForReview(succeeded));
  for (const entry of succeeded) {
    transcriptStore.addTurn({
      speaker: "Scribe",
      text:
        entry.agent_summary ??
        "Open the compare view to approve, override, or reject extracted fields.",
      kind: "review_request",
      reviewRequest: toReviewRequest(entry),
    });
  }
  return { succeeded, queued, failed };
};

const watchQueuedDocuments = (
  sessionId: string,
  queued: CachedDocument[],
  previewByName: Map<string, string>,
) => {
  if (queued.length === 0) return;

  const pendingNames = new Set(queued.map((q) => q.filename));
  const seenReady = new Set<string>();
  let attempts = 0;
  const maxAttempts = 40;

  const timer = window.setInterval(async () => {
    attempts += 1;
    try {
      const res = await getSessionDocuments(sessionId);
      for (const meta of res.documents ?? []) {
        if (!pendingNames.has(meta.original_name)) continue;
        const cached = cacheDocument({
          meta,
          previewUrl: previewByName.get(meta.original_name),
          structured_record: meta.structured_record ?? null,
        });
        if (isReviewableStatus(cached.status) && !seenReady.has(cached.filename)) {
          seenReady.add(cached.filename);
          postReviewReady(cached);
          toast.success(`Ready for review — ${cached.filename}`);
          pendingNames.delete(cached.filename);
        } else if (cached.status === "Failed") {
          toast.error(`OCR failed — ${cached.filename}`);
          transcriptStore.addTurn({
            speaker: "Scribe",
            text: `OCR failed for ${cached.filename}${cached.error ? ` — ${cached.error}` : ""}`,
            kind: "message",
          });
          pendingNames.delete(cached.filename);
        }
      }
    } catch {
      /* ignore transient poll failures */
    }

    if (pendingNames.size === 0 || attempts >= maxAttempts) {
      window.clearInterval(timer);
    }
  }, 3000);
};

export const UploadModal = ({ open, onOpenChange, onUploaded }: UploadModalProps) => {
  const { sessionId, start: startSession } = useSession();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setItems([]);
    setDragOver(false);
    setBusy(false);
  };

  const close = () => {
    onOpenChange(false);
    setTimeout(reset, 250);
  };

  const append = (files: File[]) =>
    setItems((prev) => [...prev, ...files.map((f) => prepareUpload(f))]);

  const remove = (idx: number) =>
    setItems((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = async () => {
    if (items.length === 0 || busy) return;
    setBusy(true);

    const previewByName = buildPreviewUrls(items);
    const placeholder = transcriptStore.addTurn({
      speaker: "Scribe",
      text: `Uploading ${items.length} document${items.length === 1 ? "" : "s"} for OCR review…`,
      kind: "message",
      partial: true,
    });

    try {
      const id = sessionId ?? (await startSession());
      if (!id) {
        toast.error("Could not start session — upload aborted");
        return;
      }
      const res = await uploadDocuments(id, items);
      const merged: StructuredRecord | null = res.structured_record ?? null;

      const entries = res.files.map((meta) =>
        cacheDocument({
          meta,
          previewUrl: previewByName.get(meta.original_name),
          structured_record: merged,
        }),
      );

      const { succeeded, queued, failed } = announceReview(placeholder.id, entries);

      if (failed.length > 0) {
        toast.error(
          `${failed.length} file${failed.length === 1 ? "" : "s"} failed OCR — ${failed.join(", ")}`,
        );
      }
      if (succeeded.length > 0) {
        toast.success(
          `Ready for review — ${succeeded.length} document${succeeded.length === 1 ? "" : "s"}`,
        );
      }
      if (queued.length > 0) {
        toast.success(
          `Queued for OCR extraction — ${queued.length} document${queued.length === 1 ? "" : "s"}`,
        );
        watchQueuedDocuments(id, queued, previewByName);
      }

      onUploaded?.(entries);
      onOpenChange(false);
      setTimeout(reset, 250);
    } catch (err) {
      revokeAll(previewByName.values());
      const msg = err instanceof Error ? err.message : String(err);
      transcriptStore.updateTurn(placeholder.id, `Upload failed — ${msg}`);
      toast.error(`Upload failed — ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-4 w-4" /> Upload Document
          </DialogTitle>
        </DialogHeader>

        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            append(Array.from(e.dataTransfer.files));
          }}
          className={cn(
            "flex w-full cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition-colors",
            dragOver
              ? "border-foreground/40 bg-foreground/5"
              : "border-foreground/15 bg-foreground/[0.02] hover:bg-foreground/5",
          )}
        >
          <Upload className="h-6 w-6 text-foreground/40" strokeWidth={1.8} />
          <span className="text-[13px] font-medium text-foreground/70">
            Click or drag files here
          </span>
          <span className="font-mono text-[10px] text-foreground/35">
            PDF · DOCX · JPG · PNG · DICOM
          </span>
        </button>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT}
          aria-label="Upload documents"
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            append(files);
            e.target.value = "";
          }}
        />

        {items.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1.5">
            {items.map((f, i) => {
              const ext = f.name.split(".").pop()?.toUpperCase() ?? "FILE";
              return (
                <li
                  key={`${f.name}-${i}`}
                  className="flex items-center justify-between rounded-lg border border-foreground/10 bg-foreground/[0.04] px-2.5 py-1.5"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="rounded bg-foreground/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-foreground/55">
                      {ext}
                    </span>
                    <span className="truncate text-[12px] font-medium text-foreground/80">
                      {f.name}
                    </span>
                  </div>
                  <div className="ml-2 flex shrink-0 items-center gap-2">
                    <span className="font-mono text-[10px] text-foreground/35">
                      {fmtKb(f.size)}
                    </span>
                    <button
                      type="button"
                      onClick={() => remove(i)}
                      aria-label="Remove file"
                      className="text-foreground/35 hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <DialogFooter className="mt-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="glass-chip flex items-center gap-1 rounded-full px-3 py-1.5 text-[12px] font-medium text-foreground/70 hover:text-foreground"
          >
            <Plus className="h-3 w-3" /> Add more
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={items.length === 0 || busy}
            className="flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-[12px] font-semibold text-primary-foreground shadow-[0_8px_20px_-6px_hsl(var(--primary)/0.5)] disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Analyzing…
              </>
            ) : (
              <>
                <Upload className="h-3 w-3" />
                Upload &amp; Analyze ({items.length})
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
