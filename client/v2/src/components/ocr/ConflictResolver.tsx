import { AlertTriangle, Check, Database, FileText, Pencil } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Conflict } from "@/lib/clinical";

const formatVal = (v: unknown): string => {
  if (v == null || v === "") return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
};

type Choice = "db" | "extracted" | "manual";

/**
 * Inline resolver for a single field-level conflict.
 *
 * Renders three actions:
 *   • Keep DB value
 *   • Use extracted (OCR) value
 *   • Manual edit (free-text override)
 *
 * onResolve receives the final resolved value and the choice that produced it.
 * The conflict entry can then be cleared from the record by the caller.
 */
export const ConflictResolver = ({
  conflict,
  onResolve,
  onDismiss,
  className,
}: {
  conflict: Conflict;
  onResolve: (resolution: Choice, value: unknown) => void;
  onDismiss?: () => void;
  className?: string;
}) => {
  const [manualMode, setManualMode] = useState(false);
  const [manualValue, setManualValue] = useState(formatVal(conflict.extracted_value));

  return (
    <div
      className={cn(
        "rounded-xl border border-rose-300 bg-rose-50/90 p-3 text-[12px]",
        className,
      )}
    >
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-rose-700">
        <AlertTriangle className="h-3 w-3" />
        Conflict · {conflict.field}
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-zinc-200 bg-white px-2.5 py-2">
          <div className="mb-1 flex items-center gap-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            <Database className="h-3 w-3" /> Database
          </div>
          <div className="break-words text-[12px] text-foreground">
            {formatVal(conflict.db_value)}
          </div>
        </div>
        <div className="rounded-lg border border-blue-300 bg-blue-50 px-2.5 py-2">
          <div className="mb-1 flex items-center gap-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-blue-700">
            <FileText className="h-3 w-3" /> Extracted
          </div>
          <div className="break-words text-[12px] text-foreground">
            {formatVal(conflict.extracted_value)}
          </div>
        </div>
      </div>

      {manualMode ? (
        <div className="space-y-2">
          <input
            value={manualValue}
            autoFocus
            onChange={(e) => setManualValue(e.target.value)}
            className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-[12px] outline-none focus:ring-2 focus:ring-foreground/15"
            placeholder="Enter the correct value…"
          />
          <div className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setManualMode(false)}
              className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-foreground/70 hover:bg-zinc-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => onResolve("manual", manualValue)}
              className="flex items-center gap-1 rounded-full bg-foreground px-3 py-1 text-[11px] font-medium text-background"
            >
              <Check className="h-3 w-3" /> Save override
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => onResolve("db", conflict.db_value)}
            className="flex items-center gap-1 rounded-full border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-foreground/80 hover:bg-zinc-50"
          >
            <Database className="h-3 w-3" /> Keep DB
          </button>
          <button
            type="button"
            onClick={() => onResolve("extracted", conflict.extracted_value)}
            className="flex items-center gap-1 rounded-full border border-blue-300 bg-blue-50 px-3 py-1 text-[11px] font-medium text-blue-800 hover:bg-blue-100"
          >
            <FileText className="h-3 w-3" /> Use extracted
          </button>
          <button
            type="button"
            onClick={() => setManualMode(true)}
            className="flex items-center gap-1 rounded-full border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-foreground/80 hover:bg-zinc-50"
          >
            <Pencil className="h-3 w-3" /> Edit manually
          </button>
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="ml-auto text-[11px] font-medium text-foreground/40 hover:text-foreground/70"
            >
              Skip for now
            </button>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Stacked list of every unresolved conflict in the record.
 * Use this for the side-panel or top-of-form summary view.
 */
export const ConflictsList = ({
  conflicts,
  onResolve,
  className,
}: {
  conflicts: Conflict[];
  onResolve: (field: string, resolution: Choice, value: unknown) => void;
  className?: string;
}) => {
  if (conflicts.length === 0) return null;
  return (
    <div className={cn("space-y-2", className)}>
      {conflicts.map((c) => (
        <ConflictResolver
          key={c.field}
          conflict={c}
          onResolve={(res, val) => onResolve(c.field, res, val)}
        />
      ))}
    </div>
  );
};
