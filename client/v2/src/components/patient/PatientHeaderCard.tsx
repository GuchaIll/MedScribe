import { Briefcase, Calendar, Edit3, Mail, MapPin, Phone, User } from "lucide-react";
import { Panel } from "@/components/clinical/_shared";

const stats = [
  { label: "BMI", value: "22.4", sub: "▼ 10" },
  { label: "Weight", value: "92", unit: "kg", sub: "▼ 10 kg" },
  { label: "Height", value: "175", unit: "cm" },
  { label: "Blood pressure", value: "124/80", sub: "▲ 10" },
] as const;

export const PatientHeaderCard = () => (
  <Panel>
    <div className="flex items-start gap-6">
      <div className="relative h-[120px] w-[120px] shrink-0 overflow-hidden rounded-2xl bg-gradient-to-br from-[hsl(220_60%_75%)] to-[hsl(280_60%_75%)]">
        <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1.5">
          <span className="rounded-full bg-rose-500/90 px-2 py-0.5 text-[9px] font-semibold text-white">
            Alcohol
          </span>
          <span className="rounded-full bg-amber-500/90 px-2 py-0.5 text-[9px] font-semibold text-white">
            Smoker
          </span>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-[20px] font-semibold tracking-tight">Ahmed Ali Hussain</h2>
          <button className="glass-chip flex h-7 w-7 items-center justify-center rounded-full" aria-label="Call">
            <Phone className="h-3.5 w-3.5 text-foreground/60" />
          </button>
          <button className="glass-chip flex h-7 w-7 items-center justify-center rounded-full" aria-label="Email">
            <Mail className="h-3.5 w-3.5 text-foreground/60" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-foreground/60">
          <span className="flex items-center gap-1.5"><User className="h-3.5 w-3.5" /> Male</span>
          <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> Elshiekh zayed, Giza</span>
          <span className="flex items-center gap-1.5"><Briefcase className="h-3.5 w-3.5" /> Accountant</span>
          <span className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> 12 Dec 1992 (38 years)</span>
        </div>

        <div className="mt-1 grid grid-cols-4 gap-3">
          {stats.map((s) => (
            <div key={s.label} className="glass-chip rounded-2xl px-4 py-2.5">
              <div className="flex items-baseline gap-1">
                <span className="text-[18px] font-semibold tracking-tight">{s.value}</span>
                {"unit" in s && s.unit && <span className="text-[11px] text-foreground/50">{s.unit}</span>}
              </div>
              <div className="flex items-center justify-between text-[11px] text-foreground/50">
                <span>{s.label}</span>
                {"sub" in s && s.sub && <span>{s.sub}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-col items-end gap-3">
        <button className="glass-chip flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[12.5px] font-medium">
          <Edit3 className="h-3.5 w-3.5" /> Edit
        </button>
        <div className="text-right">
          <div className="mb-1.5 text-[11.5px] text-foreground/55">Own diagnosis</div>
          <div className="flex gap-1.5">
            <span className="rounded-full bg-amber-100/70 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 border border-amber-200/60">Obesity</span>
            <span className="rounded-full bg-amber-100/70 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 border border-amber-200/60">Uncontrolled Type 2</span>
          </div>
        </div>
        <div className="text-right">
          <div className="mb-1.5 text-[11.5px] text-foreground/55">Health barriers</div>
          <div className="flex gap-1.5">
            <span className="rounded-full bg-sky-100/70 px-2.5 py-0.5 text-[11px] font-medium text-sky-800 border border-sky-200/60">Fear of medication</span>
            <span className="rounded-full bg-sky-100/70 px-2.5 py-0.5 text-[11px] font-medium text-sky-800 border border-sky-200/60">Fear of insulin</span>
          </div>
        </div>
      </div>
    </div>
  </Panel>
);
