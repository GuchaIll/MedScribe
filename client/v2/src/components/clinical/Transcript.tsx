import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ThumbsUp, ThumbsDown, RotateCcw, Sparkles, Download, FileText, ChevronDown, Pencil, Check, X, Eye, AlertTriangle, ClipboardList, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { Turn, ReviewRequest, useTranscriptTurns, transcriptStore } from "./transcriptStore";
import { ReviewChangesCard } from "@/components/pipeline/ReviewChangesCard";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

const downloadText = (filename: string, text: string) => {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

const isSectionHeading = (line: string) => {
  const t = line.trim();
  if (!t) return false;
  // "S — SUBJECTIVE", "O — Objective", "S - Subjective"
  if (/^[A-Z]\s*[—–-]\s*\S/.test(t)) return true;
  // ALL CAPS short heading
  if (/^[A-Z][A-Z0-9 /&]{2,40}$/.test(t)) return true;
  return false;
};

const FormattedScribe = ({ text }: { text: string }) => {
  const lines = text.split("\n");
  const titleLine = lines[0] ?? "";
  const rest = lines.slice(1);

  return (
    <div className="space-y-2">
      <div className="-mx-4 -mt-2.5 mb-2 rounded-t-2xl bg-accent/15 px-4 py-2 text-[12.5px] font-bold uppercase tracking-wide text-accent">
        {titleLine}
      </div>
      <div className="space-y-1.5">
        {rest.map((ln, i) => {
          if (!ln.trim()) return <div key={i} className="h-1" />;
          if (isSectionHeading(ln)) {
            return (
              <div
                key={i}
                className="-mx-1 mt-2 inline-block rounded-md bg-accent/15 px-2 py-0.5 text-[12px] font-bold uppercase tracking-wide text-accent"
              >
                {ln.trim()}
              </div>
            );
          }
          return (
            <div key={i} className="text-[13px] leading-snug text-foreground/80 whitespace-pre-wrap">
              {ln}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* ── OCR review-request card ─────────────────────────────────────────────── */

const MAX_PREVIEW_FIELDS = 6;

const fieldChangeTone: Record<NonNullable<ReviewRequest["fieldChanges"]>[number]["status"] & string, string> = {
  modified: "bg-blue-50 border-blue-200 text-blue-800",
  lowConf: "bg-yellow-50 border-yellow-200 text-yellow-800",
  conflict: "bg-rose-50 border-rose-200 text-rose-800",
};

const prettyField = (name: string) =>
  name.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const prettyValue = (v: unknown): string => {
  if (v == null || v === "") return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    const s = JSON.stringify(v);
    return s.length > 60 ? s.slice(0, 57) + "…" : s;
  } catch {
    return String(v);
  }
};

const ReviewRequestCard = ({ review }: { review: ReviewRequest }) => {
  const fields = review.fieldChanges ?? [];
  const overflow = fields.length - MAX_PREVIEW_FIELDS;
  const visible = fields.slice(0, MAX_PREVIEW_FIELDS);

  const counters: string[] = [];
  if (review.documentType) counters.push(review.documentType);
  if (typeof review.fieldsCount === "number") {
    counters.push(`${review.fieldsCount} field${review.fieldsCount === 1 ? "" : "s"}`);
  }
  if (typeof review.conflictsCount === "number" && review.conflictsCount > 0) {
    counters.push(`${review.conflictsCount} conflict${review.conflictsCount === 1 ? "" : "s"}`);
  }

  return (
    <div className="mt-3 rounded-xl border border-foreground/10 bg-white/60 p-3 shadow-[0_4px_12px_-8px_hsl(220_40%_30%/0.18)]">
      <div className="mb-2 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-foreground/55">
            <ClipboardList className="h-3 w-3" />
            Review field changes
          </div>
          {counters.length > 0 && (
            <div className="mt-0.5 truncate font-mono text-[10.5px] text-foreground/45">
              {counters.join(" · ")}
            </div>
          )}
        </div>
        <Link
          to={review.reviewUrl}
          aria-label="Open OCR comparison panel"
          title="Open compare view"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-foreground text-background shadow-[0_6px_16px_-8px_hsl(220_40%_30%/0.4)] transition-transform hover:scale-[1.04]"
        >
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {visible.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {visible.map((f, i) => {
            const tone = f.status ? fieldChangeTone[f.status] : "bg-white border-zinc-200 text-foreground/75";
            return (
              <li
                key={`${f.field_name}-${i}`}
                className={cn(
                  "flex items-center gap-2 rounded-md border px-2 py-1 text-[11.5px]",
                  tone,
                )}
              >
                {f.status === "conflict" && <AlertTriangle className="h-3 w-3 shrink-0" />}
                <span className="font-mono text-[10.5px] font-semibold opacity-80">
                  {prettyField(f.field_name)}
                </span>
                <span className="truncate">{prettyValue(f.value)}</span>
              </li>
            );
          })}
          {overflow > 0 && (
            <li className="px-2 text-[10.5px] text-foreground/50">
              + {overflow} more field{overflow === 1 ? "" : "s"} in the compare view
            </li>
          )}
        </ul>
      ) : (
        <p className="text-[11.5px] italic text-foreground/45">
          No structured fields were extracted. Open the compare view to see the original document.
        </p>
      )}
    </div>
  );
};

const Bubble = ({ turn }: { turn: Turn }) => {
  const isClinician = turn.speaker === "Clinician";
  const isScribe = turn.speaker === "Scribe";
  const isFormatted = turn.kind === "soap" || turn.kind === "summary";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(turn.text);

  if (isScribe) {
    return (
      <div className="flex animate-fade-up items-start gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-[0_4px_10px_-4px_hsl(220_40%_30%/0.25)]">
          <Sparkles className="h-3.5 w-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="glass-chip max-w-full overflow-hidden rounded-2xl rounded-tl-md px-4 py-2.5 text-[13.5px] text-foreground/80 shadow-[0_4px_12px_-6px_hsl(220_40%_30%/0.18)]">
            {editing ? (
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="min-h-[260px] resize-y border-accent/30 bg-white/60 font-mono text-[12.5px] leading-relaxed"
              />
            ) : isFormatted ? (
              <FormattedScribe text={turn.text} />
            ) : (
              <>
                <span className="mr-2 text-[10px] font-semibold uppercase tracking-wider text-accent">
                  Scribe
                </span>
                <span className="whitespace-pre-wrap">{turn.text}</span>
              </>
            )}
            {turn.reviewRequest && !editing && (
              <ReviewRequestCard review={turn.reviewRequest} />
            )}
            {turn.reviewChanges && !editing && (
              <ReviewChangesCard
                fields={turn.reviewChanges.fields}
                approved={turn.reviewChanges.approved}
                onApprove={() => {
                  transcriptStore.patchTurn(turn.id, {
                    reviewChanges: {
                      ...turn.reviewChanges!,
                      approved: true,
                    },
                  });
                  toast.success("Changes approved — patient record will be updated");
                }}
              />
            )}
          </div>
          <div className="mt-1 flex items-center gap-2 pl-1 text-[11px] text-muted-foreground">
            <span>{turn.time}</span>
            {isFormatted && !editing && (
              <>
                <button
                  onClick={() => {
                    setDraft(turn.text);
                    setEditing(true);
                  }}
                  className="ml-1 flex items-center gap-1 rounded-full px-2 py-0.5 hover:bg-white hover:text-foreground"
                >
                  <Pencil className="h-3 w-3" /> Edit
                </button>
                <button
                  onClick={() => {
                    const slug = (turn.kind ?? "note").toString();
                    downloadText(`${slug}-${turn.id}.txt`, turn.text);
                    toast.success("Downloaded");
                  }}
                  className="flex items-center gap-1 rounded-full px-2 py-0.5 hover:bg-white hover:text-foreground"
                >
                  <Download className="h-3 w-3" /> Download
                </button>
              </>
            )}
            {isFormatted && editing && (
              <>
                <button
                  onClick={() => {
                    transcriptStore.updateTurn(turn.id, draft);
                    setEditing(false);
                    toast.success("Saved");
                  }}
                  className="ml-1 flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 text-accent hover:bg-accent/25"
                >
                  <Check className="h-3 w-3" /> Save
                </button>
                <button
                  onClick={() => {
                    setDraft(turn.text);
                    setEditing(false);
                  }}
                  className="flex items-center gap-1 rounded-full px-2 py-0.5 hover:bg-white hover:text-foreground"
                >
                  <X className="h-3 w-3" /> Cancel
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`flex animate-fade-up items-end gap-3 ${
        isClinician ? "flex-row-reverse" : ""
      }`}
    >
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold shadow-[0_4px_10px_-4px_hsl(220_40%_30%/0.22)] ${
          isClinician
            ? "bg-primary text-primary-foreground"
            : "glass-chip text-foreground/80"
        }`}
      >
        {isClinician ? "Dr" : "Pt"}
      </div>
      <div className={`max-w-[70%] lg:max-w-[78%] ${isClinician ? "text-right" : ""}`}>
        <div
          className={`inline-block rounded-3xl px-4 py-2.5 text-[14px] leading-snug shadow-[0_5px_14px_-7px_hsl(220_40%_30%/0.22)] ${
            isClinician
              ? "rounded-br-md bg-primary text-primary-foreground"
              : "glass-chip rounded-bl-md text-foreground"
          } ${turn.partial ? "opacity-80" : ""}`}
        >
          <span className="whitespace-pre-wrap">{turn.text}</span>
          {turn.attachment && (() => {
            const url = turn.attachment.url;
            const inApp = url.startsWith("/");
            const sizeKB = turn.attachment.size ? `${(turn.attachment.size / 1024).toFixed(1)} KB` : "";
            const body = (
              <>
                <FileText className="h-4 w-4 shrink-0" />
                <span className="truncate">{turn.attachment.name}</span>
                {sizeKB && (
                  <span className="ml-auto text-[10.5px] text-muted-foreground">{sizeKB}</span>
                )}
              </>
            );
            const cls =
              "mt-2 flex items-center gap-2 rounded-xl bg-white/40 px-3 py-2 text-[12.5px] text-foreground/80 hover:bg-white/70";
            return inApp ? (
              <Link to={url} className={cls}>
                {body}
              </Link>
            ) : (
              <a href={url} target="_blank" rel="noopener noreferrer" className={cls}>
                {body}
              </a>
            );
          })()}
          {turn.partial && (
            <span className="ml-1 inline-block h-3.5 w-[2px] animate-pulse bg-current align-middle" />
          )}
        </div>
        <div
          className={`mt-1 text-[11px] text-muted-foreground ${
            isClinician ? "pr-2" : "pl-2"
          }`}
        >
          {turn.speaker} · {turn.time}
        </div>
      </div>
    </div>
  );
};

export const buildSoapText = () => {
  const turns = transcriptStore.getSnapshot();
  const lines = [
    "SESSION SUMMARY — Encounter #4821",
    `Generated: ${new Date().toLocaleString()}`,
    "",
    "TRANSCRIPT",
    "----------",
    ...turns.map((t) => `[${t.time}] ${t.speaker}: ${t.text}`),
    "",
    "SOAP NOTE",
    "==========",
    "",
    "S — SUBJECTIVE (History)",
    "------------------------",
    "HPI: Exertional chest pressure × 3 days. Dull, retrosternal, provoked by climbing stairs.",
    "  Associated mild dyspnea and a single episode of nausea. No diaphoresis, no radiation.",
    "  Source: patient.",
    "Pertinent PMH: Hypertension (well controlled). No prior cardiac history.",
    "Pertinent ROS: Denies palpitations, syncope, orthopnea, lower-extremity edema.",
    "Current medications: Lisinopril 10 mg PO daily.",
    "",
    "O — OBJECTIVE (Exam & Data)",
    "---------------------------",
    "Vitals: BP 132/84, HR 78, RR 16, SpO2 98% RA, T 36.8°C.",
    "Focused exam: Alert, NAD. Cardiac RRR, no murmurs/rubs/gallops. Lungs CTA bilaterally.",
    "  Chest wall non-tender. No JVD. Extremities warm, no edema.",
    "Studies at visit: ECG pending. Troponin pending. Lipid panel pending.",
    "",
    "A — ASSESSMENT / PROBLEM LIST",
    "-----------------------------",
    "Assessment: Middle-aged patient with new exertional chest pressure concerning for stable angina.",
    "Problem list:",
    "  1. Exertional chest pressure — new",
    "  2. Hypertension — stable",
    "Differential diagnoses (major new problem):",
    "  • Stable angina pectoris secondary to coronary artery disease",
    "  • Musculoskeletal chest wall pain",
    "  • Gastroesophageal reflux disease",
    "",
    "P — PLAN",
    "--------",
    "Diagnostic: 12-lead ECG, high-sensitivity troponin, lipid panel, HbA1c. Consider stress",
    "  testing if initial workup unrevealing.",
    "Treatment: Initiate ASA 81 mg daily pending workup. Continue antihypertensive regimen.",
    "Patient education: Reviewed red-flag symptoms (rest pain, syncope, severe dyspnea) —",
    "  return to ED immediately if these occur.",
    "Follow-up: Clinic visit in 1 week to review results; cardiology referral if positive workup.",
  ];
  return lines.join("\n");
};

const buildTranscriptText = () => {
  const turns = transcriptStore.getSnapshot();
  return [
    "TRANSCRIPT — Encounter #4821",
    `Generated: ${new Date().toLocaleString()}`,
    "",
    ...turns.map((t) => `[${t.time}] ${t.speaker}: ${t.text}`),
  ].join("\n");
};

const buildDischargeText = () => {
  return [
    "DISCHARGE NOTE — Encounter #4821",
    `Generated: ${new Date().toLocaleString()}`,
    "",
    "Diagnosis: Exertional chest pressure — workup pending; stable hypertension.",
    "",
    "Discharge Instructions:",
    "• Begin ASA 81 mg PO daily.",
    "• Continue Lisinopril 10 mg PO daily.",
    "• Avoid strenuous exertion until cardiology workup complete.",
    "",
    "Red-flag Symptoms — Return to ED immediately for:",
    "• Chest pain at rest or worsening pressure",
    "• Syncope or near-syncope",
    "• Severe dyspnea, diaphoresis, or radiating arm/jaw pain",
    "",
    "Follow-up:",
    "• Primary care in 1 week to review labs and ECG.",
    "• Cardiology referral pending workup results.",
  ].join("\n");
};

// --- PDF generation with headings, word wrap, multi-page ---
const PDF_WIDTH = 612;
const PDF_HEIGHT = 792;
const PDF_MARGIN_X = 56;
const PDF_MARGIN_Y = 56;

const escPdf = (s: string) =>
  s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");

// Approximate character width for Helvetica at given font size
const charWidth = (fontSize: number) => fontSize * 0.5;

const wrapLine = (line: string, fontSize: number, maxWidth: number) => {
  const cw = charWidth(fontSize);
  const maxChars = Math.max(10, Math.floor(maxWidth / cw));
  if (line.length <= maxChars) return [line];
  const words = line.split(/(\s+)/);
  const out: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + w).length > maxChars) {
      if (cur.trim()) out.push(cur.trimEnd());
      cur = w.trimStart();
      if (cur.length > maxChars) {
        // hard break very long token
        while (cur.length > maxChars) {
          out.push(cur.slice(0, maxChars));
          cur = cur.slice(maxChars);
        }
      }
    } else {
      cur += w;
    }
  }
  if (cur.trim()) out.push(cur.trimEnd());
  return out;
};

type Block =
  | { kind: "title"; text: string }
  | { kind: "h1"; text: string }
  | { kind: "h2"; text: string }
  | { kind: "body"; text: string }
  | { kind: "spacer" };

const styleFor = (b: Block) => {
  switch (b.kind) {
    case "title":
      return { font: "F2", size: 18, leading: 24, after: 8 };
    case "h1":
      return { font: "F2", size: 13, leading: 18, after: 4 };
    case "h2":
      return { font: "F2", size: 11, leading: 16, after: 2 };
    case "body":
      return { font: "F1", size: 10, leading: 14, after: 0 };
    case "spacer":
      return { font: "F1", size: 10, leading: 8, after: 0 };
  }
};

const parseBlocks = (text: string, docTitle: string): Block[] => {
  const blocks: Block[] = [{ kind: "title", text: docTitle }];
  const lines = text.split("\n");
  for (const raw of lines) {
    const ln = raw.replace(/\t/g, "  ");
    const trimmed = ln.trim();
    if (!trimmed) {
      blocks.push({ kind: "spacer" });
      continue;
    }
    // Skip pure separator lines
    if (/^[-=]{3,}$/.test(trimmed)) continue;
    // SOAP-style major heading: "S — SUBJECTIVE..."
    if (/^[A-Z]\s*[—–-]\s*[A-Za-z]/.test(trimmed)) {
      blocks.push({ kind: "h1", text: trimmed });
      continue;
    }
    // Section sub-heading detected via ALL CAPS
    if (/^[A-Z][A-Z0-9 /&]{2,40}:?$/.test(trimmed)) {
      blocks.push({ kind: "h1", text: trimmed });
      continue;
    }
    // "Label:" inline subheading at start of line
    const m = trimmed.match(/^([A-Z][A-Za-z /]{2,30}):\s*(.*)$/);
    if (m && m[2]) {
      blocks.push({ kind: "h2", text: m[1] });
      blocks.push({ kind: "body", text: m[2] });
      continue;
    }
    blocks.push({ kind: "body", text: ln });
  }
  return blocks;
};

const renderPdf = (blocks: Block[]) => {
  const maxWidth = PDF_WIDTH - PDF_MARGIN_X * 2;
  const pages: string[] = [];
  let stream = "";
  let y = PDF_HEIGHT - PDF_MARGIN_Y;
  let curFont = "";
  let curSize = 0;

  const newPage = () => {
    if (stream) pages.push(stream);
    stream = "";
    y = PDF_HEIGHT - PDF_MARGIN_Y;
    curFont = "";
    curSize = 0;
  };

  for (const b of blocks) {
    const s = styleFor(b);
    if (b.kind === "spacer") {
      y -= s.leading;
      if (y < PDF_MARGIN_Y) newPage();
      continue;
    }
    const lines = wrapLine(b.text, s.size, maxWidth);
    for (const ln of lines) {
      if (y - s.leading < PDF_MARGIN_Y) newPage();
      if (curFont !== s.font || curSize !== s.size) {
        stream += `/${s.font} ${s.size} Tf\n`;
        curFont = s.font;
        curSize = s.size;
      }
      stream += `BT ${PDF_MARGIN_X} ${y - s.size} Td (${escPdf(ln)}) Tj ET\n`;
      y -= s.leading;
    }
    y -= s.after;
  }
  if (stream) pages.push(stream);
  if (pages.length === 0) pages.push("");

  // Build PDF objects
  const objects: string[] = [];
  objects.push("<< /Type /Catalog /Pages 2 0 R >>");
  // Pages object id 2; page object ids start after content/font objects
  // We'll lay out: 1 catalog, 2 pages, 3 F1, 4 F2, then for each page: content + page obj
  const fontF1Id = 3;
  const fontF2Id = 4;
  const firstPageDataId = 5;
  const kids: number[] = [];
  for (let i = 0; i < pages.length; i++) {
    kids.push(firstPageDataId + 1 + i * 2); // page object id
  }
  objects.push(
    `<< /Type /Pages /Kids [${kids.map((k) => `${k} 0 R`).join(" ")}] /Count ${pages.length} >>`
  );
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");
  for (let i = 0; i < pages.length; i++) {
    const contentId = firstPageDataId + i * 2;
    const pageId = contentId + 1;
    const content = pages[i];
    objects.push(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PDF_WIDTH} ${PDF_HEIGHT}] /Contents ${contentId} 0 R /Resources << /Font << /F1 ${fontF1Id} 0 R /F2 ${fontF2Id} 0 R >> >> >>`
    );
  }

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((obj, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${obj}\nendobj\n`;
  });
  const xrefStart = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.forEach((o) => {
    pdf += `${o.toString().padStart(10, "0")} 00000 n \n`;
  });
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  return pdf;
};

type ExportKind = "transcript" | "soap" | "discharge";

const buildExportBody = (kind: ExportKind): { title: string; body: string } => {
  const turns = transcriptStore.getSnapshot();
  if (kind === "transcript") {
    return { title: "Transcript — Encounter #4821", body: buildTranscriptText() };
  }
  if (kind === "soap") {
    const latest = [...turns].reverse().find((t) => t.kind === "soap");
    return { title: "SOAP Note — Encounter #4821", body: latest ? latest.text : buildSoapText() };
  }
  const latest = [...turns]
    .reverse()
    .find((t) => t.kind === "soap" && /discharge/i.test(t.text));
  return { title: "Discharge Note — Encounter #4821", body: latest ? latest.text : buildDischargeText() };
};

const buildPdfUrl = (title: string, body: string) => {
  const blocks = parseBlocks(body, title);
  const pdf = renderPdf(blocks);
  const blob = new Blob([pdf], { type: "application/pdf" });
  return URL.createObjectURL(blob);
};


export const Transcript = () => {
  const turns = useTranscriptTurns();
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<{
    kind: ExportKind;
    url: string;
    filename: string;
    title: string;
    body: string;
  } | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const openPreview = (kind: ExportKind) => {
    if (preview) URL.revokeObjectURL(preview.url);
    const { title, body } = buildExportBody(kind);
    const url = buildPdfUrl(title, body);
    setPreview({ kind, url, filename: `${kind}-4821-${Date.now()}.pdf`, title, body });
  };

  const updatePreviewBody = (body: string) => {
    setPreview((prev) => {
      if (!prev) return prev;
      URL.revokeObjectURL(prev.url);
      const url = buildPdfUrl(prev.title, body);
      return { ...prev, body, url };
    });
  };

  const closePreview = () => {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const downloadPreview = () => {
    if (!preview) return;
    const a = document.createElement("a");
    a.href = preview.url;
    a.download = preview.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast.success(`${preview.title} downloaded`);
    closePreview();
  };


  return (
    <div className="flex h-full flex-col">
      <header className="mb-4 flex items-center justify-between gap-3">
        <span className="w-[120px]" />
        <div className="glass-chip rounded-full px-4 py-1.5 text-[13px] font-medium text-foreground/80">
          Live Transcription · Encounter #4821
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="glass-chip flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium text-foreground/80 transition-all hover:bg-white">
              <Download className="h-3.5 w-3.5" /> Export
              <ChevronDown className="h-3 w-3" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem onClick={() => openPreview("transcript")}>
              Transcription
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => openPreview("soap")}>
              SOAP note
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => openPreview("discharge")}>
              Discharge note
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto pr-2">
        {turns.map((t) => (
          <Bubble key={t.id} turn={t} />
        ))}
        <div ref={endRef} />
      </div>

      <div className="mt-4 flex items-center justify-between px-2 text-muted-foreground">
        <button className="flex items-center gap-1.5 text-xs hover:text-foreground">
          <RotateCcw className="h-3.5 w-3.5" /> Regenerate summary
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="Mark this summary as helpful"
            className="glass-chip flex h-8 w-8 items-center justify-center rounded-full hover:text-foreground"
          >
            <ThumbsUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Mark this summary as unhelpful"
            className="glass-chip flex h-8 w-8 items-center justify-center rounded-full hover:text-foreground"
          >
            <ThumbsDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <Dialog open={!!preview} onOpenChange={(open) => !open && closePreview()}>
        <DialogContent className="max-w-4xl p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-3">
            <DialogTitle className="flex items-center gap-2 text-[15px]">
              <Eye className="h-4 w-4 text-accent" />
              Preview · {preview?.title}
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 bg-muted/40 px-6 pb-2">
            {preview && (
              <>
                <Textarea
                  value={preview.body}
                  onChange={(e) => updatePreviewBody(e.target.value)}
                  className="h-[70vh] resize-none rounded-lg border-border bg-white font-mono text-[12px] leading-relaxed"
                />
                <iframe
                  title="PDF preview"
                  src={preview.url}
                  className="h-[70vh] w-full rounded-lg border border-border bg-white"
                />
              </>
            )}
          </div>
          <DialogFooter className="px-6 py-4 border-t bg-background">
            <button
              onClick={closePreview}
              className="glass-chip rounded-full px-4 py-1.5 text-[12.5px] font-medium text-foreground/80 hover:bg-white"
            >
              Cancel
            </button>
            <button
              onClick={downloadPreview}
              className="flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-[12.5px] font-medium text-primary-foreground shadow-[0_6px_16px_-8px_hsl(var(--primary)/0.6)] hover:opacity-95"
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
