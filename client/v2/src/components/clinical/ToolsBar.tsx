import { useState } from "react";
import { Upload, User, ClipboardList, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { transcriptStore } from "./transcriptStore";
import { UploadModal } from "@/components/ocr/UploadModal";
import { usePipelineRun } from "@/hooks/usePipelineRun";
import { cn } from "@/lib/utils";

const PATIENT_SUMMARY = `Patient Snapshot — Jordan Reyes, 58F
• Active conditions: Type 2 Diabetes (since 2022, last A1c 8.4), Hypertension, Chronic thyroid disorder, prior Angina pectoris.
• Medications: Metformin 1000 mg BID, Amaryl 1 mg daily, Lisinopril 10 mg daily, Levothyroxine 50 mcg daily, ASA 81 mg daily.
• Allergies: Penicillin (hives), Sulfa drugs (rash). NKDA otherwise.
• Recent vitals: BP 132/84, HR 78, BMI 29.1. Last fasting BGL 168 mg/dL.
• Key risks: cardiovascular (prior angina), glycemic variability, partial medication adherence (Amaryl).`;

const SOAP_DRAFT = `SOAP Draft — Encounter #4821

S — Subjective
HPI: Exertional chest pressure × 3 days, dull, retrosternal, provoked by stairs. Mild dyspnea, single nausea episode. No diaphoresis, no radiation.
PMH: HTN (controlled), T2DM. ROS otherwise negative for palpitations, syncope, orthopnea, edema.
Meds: Lisinopril 10 mg daily, Metformin 1000 mg BID.

O — Objective
Vitals: BP 132/84, HR 78, RR 16, SpO2 98% RA, T 36.8 °C.
Exam: Alert, NAD. RRR, no m/r/g. Lungs CTA. Chest wall non-tender. No JVD/edema.
Pending: 12-lead ECG, hs-troponin, lipid panel, HbA1c.

A — Assessment
1. New exertional chest pressure — concern for stable angina.
2. HTN — stable.
DDx: stable angina, MSK chest wall pain, GERD.

P — Plan
• ECG + hs-troponin now; lipid panel and HbA1c today.
• Start ASA 81 mg daily pending workup; continue lisinopril.
• Patient education on red-flag symptoms; return to ED for rest pain, syncope, severe dyspnea.
• Follow-up in 1 week; cardiology referral if workup positive.`;

const DISCHARGE_NOTE = `Discharge Note — Encounter #4821

Diagnosis
Exertional chest pressure — workup pending. Stable hypertension.

Discharge Instructions
• Begin ASA 81 mg PO daily.
• Continue Lisinopril 10 mg PO daily.
• Avoid strenuous exertion until cardiology workup complete.

Red-flag Symptoms — Return to ED for
• Chest pain at rest or worsening pressure
• Syncope or near-syncope
• Severe dyspnea, diaphoresis, or radiating arm/jaw pain

Follow-up
• Primary care in 1 week to review labs and ECG.
• Cardiology referral pending workup results.`;

export const ToolsBar = () => {
  const [uploadOpen, setUploadOpen] = useState(false);
  const { run: runPipeline, running } = usePipelineRun();

  const handleUploadClick = () => setUploadOpen(true);

  // UploadModal manages its own transcript turns + status reporting, so the
  // tools bar just needs to open it.

  const handlePatientProfile = () => {
    transcriptStore.addTurn({
      speaker: "Scribe",
      text: PATIENT_SUMMARY,
      kind: "summary",
    });
    toast.success("Patient summary added");
  };

  const handleSessionSummary = async () => {
    if (running) return;
    await runPipeline();
  };

  const tools: Array<{
    icon: typeof Upload;
    label: string;
    sub: string;
    onClick: () => void;
    disabled?: boolean;
    busy?: boolean;
  }> = [
    { icon: Upload, label: "Upload Document", sub: "OCR analysis", onClick: handleUploadClick },
    { icon: User, label: "Patient Profile", sub: "Encounter context", onClick: handlePatientProfile },
    {
      icon: ClipboardList,
      label: running ? "Generating SOAP…" : "Session Summary",
      sub: running ? "Pipeline running" : "Run 16-node pipeline",
      onClick: handleSessionSummary,
      disabled: running,
      busy: running,
    },
    {
      icon: FileText,
      label: "Discharge Note",
      sub: "Patient instructions (mock)",
      onClick: () => {
        transcriptStore.addTurn({
          speaker: "Scribe",
          text: DISCHARGE_NOTE,
          kind: "soap",
        });
        toast.success("Discharge note added");
      },
    },
  ];

  return (
    <div className="flex w-full items-center gap-2 overflow-x-auto px-0.5 pb-1 md:gap-3">
      <UploadModal open={uploadOpen} onOpenChange={setUploadOpen} />
      {tools.map(({ icon: Icon, label, sub, onClick, disabled, busy }) => (
        <button
          key={label}
          type="button"
          onClick={onClick}
          disabled={disabled}
          className={cn(
            "glass-chip group flex flex-1 min-w-[120px] items-center gap-2 rounded-full px-2.5 py-2 text-left transition-all hover:bg-white lg:min-w-[160px] lg:gap-2.5 lg:px-3.5 lg:py-2.5",
            disabled && "cursor-not-allowed opacity-70 hover:bg-transparent",
          )}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-white to-secondary text-foreground/80 md:h-9 md:w-9">
            {busy ? (
              <Loader2 className="h-[15px] w-[15px] animate-spin" strokeWidth={1.8} />
            ) : (
              <Icon className="h-[15px] w-[15px]" strokeWidth={1.8} />
            )}
          </span>
          <span className="flex-1 leading-tight">
            <span className="block text-[12.5px] font-medium">{label}</span>
            <span className="block text-[10.5px] text-muted-foreground">{sub}</span>
          </span>
        </button>
      ))}
    </div>
  );
};
