import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, Save } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  buildRecordFromFieldChanges,
  buildStatusIndex,
  buildSummary,
  EMPTY_RECORD,
  setPath,
  type Conflict,
  type FieldChange,
  type StructuredRecord,
} from "@/lib/clinical";
import { FieldComparator } from "./FieldComparator";
import { ConflictsList } from "./ConflictResolver";

export type DocumentViewerDoc = {
  documentId?: string;
  name: string;
  type?: string;
  documentType?: string;
  date?: string;
  confidence?: number;
  status?: "Pending" | "Processed" | "Conflicts" | string;
  previewUrl?: string;
  fieldChanges?: FieldChange[];
};

export type DocumentViewerProps = {
  doc: DocumentViewerDoc;
  /** The consolidated record from the backend; when absent, fieldChanges is used. */
  structuredRecord?: StructuredRecord | null;
  /** Called when the clinician hits "Save changes". */
  onSave?: (record: StructuredRecord) => void | Promise<void>;
  /** Optional back-affordance (e.g. close the modal / navigate). */
  onBack?: () => void;
};

const statusToneFor = (s: string | undefined) =>
  s === "Processed"
    ? "bg-emerald-100/80 text-emerald-700 border-emerald-200"
    : s === "Conflicts"
    ? "bg-rose-100/80 text-rose-700 border-rose-200"
    : "bg-amber-100/80 text-amber-700 border-amber-200";

/**
 * Split-pane shell: original document on the left, editable consolidated
 * record on the right with inline conflict-resolution affordances.
 */
export const DocumentViewer = ({ doc, structuredRecord, onSave, onBack }: DocumentViewerProps) => {
  const [rec, setRec] = useState<StructuredRecord>(() => {
    const base =
      structuredRecord ?? buildRecordFromFieldChanges(doc.fieldChanges) ?? EMPTY_RECORD;
    return JSON.parse(JSON.stringify(base));
  });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  // Re-sync when a fresh structuredRecord arrives (OCR finishes after the
  // panel is already open). Keyed on a stable docId so per-keystroke edits to
  // doc.fieldChanges don't blow away the form.
  const docId = doc.documentId ?? doc.name;
  useEffect(() => {
    if (structuredRecord) {
      setRec(JSON.parse(JSON.stringify(structuredRecord)));
      setDirty(false);
    } else if (doc.fieldChanges?.length) {
      const built = buildRecordFromFieldChanges(doc.fieldChanges);
      if (built) {
        setRec(JSON.parse(JSON.stringify(built)));
        setDirty(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structuredRecord, docId]);

  const status = useMemo(() => buildStatusIndex(rec), [rec]);
  const summary = useMemo(() => buildSummary(rec), [rec]);

  const handleChange = (next: StructuredRecord) => {
    setRec(next);
    setDirty(true);
  };

  const handleResolveConflict = (field: string, resolution: Conflict["resolution"], value: unknown) => {
    setRec((prev) => {
      const withValue = setPath(prev, field, value);
      // strip the conflict entry once resolved
      const conflicts = (withValue._conflicts || []).filter((c) => c.field !== field);
      return { ...withValue, _conflicts: conflicts };
    });
    setDirty(true);
    toast.success(`Resolved ${field} (${resolution})`);
  };

  const handleSave = async () => {
    if (!onSave) return;
    setSaving(true);
    try {
      await onSave(rec);
      setDirty(false);
      toast.success("Record saved");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Save failed — ${msg}`);
    } finally {
      setSaving(false);
    }
  };

  const fileName = doc.name || "Document";
  const isImage = /\.(png|jpe?g|gif|bmp|webp)$/i.test(fileName);
  const isPdf = /\.pdf$/i.test(fileName);
  const conflicts = rec._conflicts ?? [];

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* ── Left: document preview ─────────────────────────────────────── */}
      <div className="flex w-[42%] shrink-0 flex-col border-r border-foreground/10 bg-zinc-50">
        <div className="flex shrink-0 items-center gap-2.5 border-b border-foreground/10 bg-white px-4 py-2.5">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              title="Back"
              className="glass-chip flex h-7 w-7 items-center justify-center rounded-full text-foreground/70 hover:text-foreground"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-semibold">{fileName}</div>
            <div className="font-mono text-[10px] text-foreground/45">
              {doc.documentType || doc.type || ""}
              {doc.date ? ` · ${doc.date}` : ""}
              {doc.confidence != null ? ` · ${doc.confidence}% confidence` : ""}
            </div>
          </div>
          {doc.status && (
            <span
              className={cn(
                "rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider",
                statusToneFor(doc.status),
              )}
            >
              {doc.status}
            </span>
          )}
        </div>

        <div className="flex min-h-0 flex-1 items-stretch justify-center overflow-hidden">
          {doc.previewUrl && isPdf ? (
            <iframe
              src={doc.previewUrl}
              title={fileName}
              className="h-full w-full border-0"
            />
          ) : doc.previewUrl && isImage ? (
            <div className="flex flex-1 items-center justify-center p-4">
              <img
                src={doc.previewUrl}
                alt={fileName}
                className="max-h-full max-w-full rounded-lg object-contain shadow-[0_2px_16px_rgba(0,0,0,0.12)]"
              />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 text-foreground/40">
              <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-foreground/5 font-mono text-[13px] font-bold text-foreground/55">
                {doc.type?.toUpperCase() || "DOC"}
              </div>
              <span className="max-w-[200px] text-center font-mono text-[12px] leading-relaxed text-foreground/45">
                {doc.previewUrl
                  ? "Loading preview…"
                  : "Preview not available. Document was processed server-side."}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Right: consolidated record ─────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-white text-foreground">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-foreground/10 bg-white px-6 py-3">
          <div>
            <div className="text-[11.5px] font-bold tracking-wide">Consolidated Record</div>
            <div className="mt-0.5 font-mono text-[10px] text-foreground/45">
              {status.modifiedSet.size > 0 && (
                <span className="mr-2.5 text-blue-600">
                  ● {status.modifiedSet.size} extracted
                </span>
              )}
              {status.lowConfSet.size > 0 && (
                <span className="mr-2.5 text-amber-600">
                  ⚠ {status.lowConfSet.size} uncertain
                </span>
              )}
              {status.conflictMap.size > 0 && (
                <span className="text-rose-600">
                  ✕ {status.conflictMap.size} conflict
                  {status.conflictMap.size !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
          {dirty && onSave && (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1.5 rounded-full bg-foreground px-3.5 py-1.5 text-[11.5px] font-semibold text-background disabled:opacity-60"
            >
              <Save className="h-3 w-3" />
              {saving ? "Saving…" : "Save changes"}
            </button>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {summary && (
            <div className="mb-4 rounded-xl border border-foreground/10 bg-foreground/[0.03] p-3.5">
              <div className="mb-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-foreground/45">
                Summary
              </div>
              <p className="text-[12px] leading-relaxed text-foreground/80">{summary}</p>
            </div>
          )}

          {conflicts.length > 0 && (
            <div className="mb-5">
              <div className="mb-2 font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-rose-700">
                Conflicts to resolve ({conflicts.length})
              </div>
              <ConflictsList conflicts={conflicts} onResolve={handleResolveConflict} />
            </div>
          )}

          <FieldComparator record={rec} onChange={handleChange} />
        </div>
      </div>
    </div>
  );
};
