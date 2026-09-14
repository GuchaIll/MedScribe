import { Activity, Droplet, FileText, Flame, Scissors, Users } from "lucide-react";
import { Panel, SectionHeader } from "@/components/clinical/_shared";

const items = [
  { icon: Activity, label: "chronic disease", value: "IHD, Obesity, Chronic thyroid disorder" },
  { icon: Droplet, label: "Diabetes Emergencies", value: "Diabetic Ketoacidosis" },
  { icon: Scissors, label: "Sugery", value: "Liposuction" },
  { icon: Users, label: "Family disease", value: "Obesity (Father)" },
];

export const MedicalHistoryPanel = () => (
  <Panel className="col-span-2">
    <SectionHeader icon={FileText} title="Medical history" />
    <div className="grid grid-cols-2 gap-3">
      {items.map((m) => (
        <div key={m.label} className="glass-chip rounded-2xl p-3.5">
          <div className="mb-1 flex items-center gap-2 text-[11.5px] text-foreground/55">
            <m.icon className="h-3.5 w-3.5" /> {m.label}
          </div>
          <div className="text-[13px] font-medium">{m.value}</div>
        </div>
      ))}
      <div className="col-span-2 glass-chip rounded-2xl p-3.5">
        <div className="mb-1 flex items-center gap-2 text-[11.5px] text-foreground/55">
          <Flame className="h-3.5 w-3.5" /> Diabetes related complication
        </div>
        <div className="text-[13px] font-medium">
          Nephropathy, Neuropathy, Retinopathy, Diabetic foot, Sexual dysfunction
        </div>
      </div>
    </div>
  </Panel>
);
