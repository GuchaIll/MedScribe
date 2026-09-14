import { cn } from "@/lib/utils";
import { LOW_CONF, STATUS_CLASSES, type Conflict, type FieldStatus } from "@/lib/clinical";

const baseInput =
  "w-full rounded-md border px-2.5 py-1.5 text-[12px] leading-relaxed text-foreground placeholder:text-foreground/35 outline-none focus:ring-2 focus:ring-foreground/15 transition-colors";
const baseTextarea = `${baseInput} min-h-[56px] resize-y`;

const titleFor = (status: FieldStatus, conflict?: Conflict) => {
  if (status === "conflict" && conflict) {
    const db = String(conflict.db_value ?? "—");
    const ex = String(conflict.extracted_value ?? "—");
    return `DB: ${db}  |  Extracted: ${ex}`;
  }
  if (status === "lowConf") return `Low confidence (< ${Math.round(LOW_CONF * 100)}%)`;
  if (status === "modified") return "Populated from extracted data";
  return undefined;
};

export const FieldLabel = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-foreground/55">
    {children}
  </div>
);

export const SectionHeading = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2 mt-5 border-b border-foreground/10 pb-1 font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-foreground/70">
    {children}
  </div>
);

export const SubHeading = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-1.5 mt-3 font-mono text-[10px] font-bold uppercase tracking-[0.08em] text-foreground/50">
    {children}
  </div>
);

export const KVGrid = ({ children }: { children: React.ReactNode }) => (
  <div className="grid grid-cols-2 gap-x-3.5 gap-y-1.5">{children}</div>
);

export type FieldProps = {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  placeholder?: string;
  status?: FieldStatus;
  conflict?: Conflict;
};

/**
 * Editable field whose border/background reflects its OCR status.
 * normal | modified (blue) | lowConf (yellow) | conflict (red).
 */
export const Field = ({
  label,
  value,
  onChange,
  multiline,
  placeholder,
  status = "normal",
  conflict,
}: FieldProps) => {
  const title = titleFor(status, conflict);
  const cls = cn(multiline ? baseTextarea : baseInput, STATUS_CLASSES[status]);
  return (
    <label className="mb-2.5 block">
      {label && <FieldLabel>{label}</FieldLabel>}
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? "Not documented"}
          title={title}
          className={cls}
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? "Not documented"}
          title={title}
          className={cls}
        />
      )}
    </label>
  );
};

/**
 * Borderless variant for list-item editors that already have their own border.
 */
export const InlineField = ({
  value,
  onChange,
  status = "normal",
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  status?: FieldStatus;
  placeholder?: string;
}) => (
  <input
    type="text"
    value={value}
    onChange={(e) => onChange(e.target.value)}
    placeholder={placeholder ?? ""}
    className={cn(baseInput, STATUS_CLASSES[status])}
  />
);
