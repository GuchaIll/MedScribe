/**
 * Post-pipeline "Review patient record changes" card.
 *
 * Renders inside a Scribe bubble after the LangGraph pipeline completes with
 * `validation_report.needs_review === true`. Lists each affected section with
 * the new value, a status tone (ok / warning / conflict / unchanged), and a
 * reason line. A single Approve button commits the batch.
 *
 * Phase 4 wires `onApprove` to a local "approved: true" flag. A future
 * iteration will POST to /api/session/:id/record (or similar) to durably
 * commit the approved record.
 */
import { AlertTriangle, Check, ClipboardCheck, FileSignature } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReviewField, ReviewFieldStatus } from "@/lib/pipelineReview";

const TONE: Record<ReviewFieldStatus, { row: string; chip: string; dot: string; label: string }> = {
  ok: {
    row: "bg-emerald-50/60 border-emerald-200",
    chip: "bg-emerald-100/80 text-emerald-800",
    dot: "bg-emerald-500",
    label: "Updated",
  },
  warning: {
    row: "bg-amber-50/70 border-amber-200",
    chip: "bg-amber-100/80 text-amber-800",
    dot: "bg-amber-500",
    label: "Uncertain",
  },
  conflict: {
    row: "bg-rose-50/70 border-rose-200",
    chip: "bg-rose-100/80 text-rose-800",
    dot: "bg-rose-500",
    label: "Conflict",
  },
  unchanged: {
    row: "bg-white/50 border-foreground/10",
    chip: "bg-foreground/5 text-foreground/55",
    dot: "bg-foreground/30",
    label: "Unchanged",
  },
};

export type ReviewChangesCardProps = {
  fields: ReviewField[];
  approved?: boolean;
  onApprove: () => void;
  /** Optional secondary action (e.g. open the compare view). */
  onReviewIndividually?: () => void;
};

export const ReviewChangesCard = ({
  fields,
  approved,
  onApprove,
  onReviewIndividually,
}: ReviewChangesCardProps) => {
  const conflicts = fields.filter((f) => f.status === "conflict").length;
  const warnings = fields.filter((f) => f.status === "warning").length;
  const updates = fields.filter((f) => f.status === "ok").length;

  return (
    <div className="mt-3 rounded-xl border border-foreground/10 bg-white/70 p-3 shadow-[0_4px_12px_-8px_hsl(220_40%_30%/0.18)]">
      <header className="mb-2 flex items-start gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground/85 text-background">
          <FileSignature className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-foreground/55">
            Review patient record changes
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] text-foreground/45">
            {updates > 0 && <span className="mr-2 text-emerald-700">{updates} updated</span>}
            {warnings > 0 && <span className="mr-2 text-amber-700">{warnings} uncertain</span>}
            {conflicts > 0 && <span className="text-rose-700">{conflicts} conflict{conflicts === 1 ? "" : "s"}</span>}
            {updates + warnings + conflicts === 0 && "No clinical fields changed."}
          </div>
        </div>
      </header>

      {/* Legend */}
      <div className="mb-2 flex flex-wrap gap-2 rounded-lg bg-foreground/[0.03] px-2 py-1">
        {(["ok", "warning", "conflict", "unchanged"] as ReviewFieldStatus[]).map((s) => (
          <span
            key={s}
            className="flex items-center gap-1 font-mono text-[9.5px] uppercase tracking-wider text-foreground/45"
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", TONE[s].dot)} />
            {TONE[s].label}
          </span>
        ))}
      </div>

      {/* Field rows */}
      <ul className="max-h-[360px] overflow-y-auto pr-1">
        {fields.map((f) => {
          const tone = TONE[f.status];
          return (
            <li
              key={f.title}
              className={cn(
                "mb-1.5 rounded-lg border px-3 py-2 transition-colors",
                tone.row,
              )}
            >
              <div className="mb-0.5 flex items-center justify-between gap-2">
                <span className="font-mono text-[10.5px] font-semibold uppercase tracking-wider text-foreground/65">
                  {f.title}
                </span>
                <span
                  className={cn(
                    "flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[9.5px] font-bold uppercase tracking-wider",
                    tone.chip,
                  )}
                >
                  {f.status === "conflict" && <AlertTriangle className="h-2.5 w-2.5" />}
                  {tone.label}
                </span>
              </div>
              <div className="whitespace-pre-wrap text-[12px] leading-snug text-foreground/85">
                {f.value}
              </div>
              {f.reason && (
                <div className="mt-1 font-mono text-[10px] text-foreground/45">{f.reason}</div>
              )}
            </li>
          );
        })}
      </ul>

      <footer className="mt-2 flex items-center justify-end gap-1.5">
        {onReviewIndividually && (
          <button
            type="button"
            onClick={onReviewIndividually}
            className="glass-chip rounded-full px-3 py-1 text-[11px] font-medium text-foreground/70 hover:text-foreground"
          >
            Review individually
          </button>
        )}
        <button
          type="button"
          onClick={onApprove}
          disabled={approved}
          className={cn(
            "flex items-center gap-1.5 rounded-full px-3.5 py-1 text-[11.5px] font-semibold transition-colors",
            approved
              ? "bg-emerald-100/90 text-emerald-800"
              : "bg-foreground text-background hover:opacity-90",
          )}
        >
          {approved ? (
            <>
              <ClipboardCheck className="h-3 w-3" /> Approved
            </>
          ) : (
            <>
              <Check className="h-3 w-3" /> Approve changes
            </>
          )}
        </button>
      </footer>
    </div>
  );
};
