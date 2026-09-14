import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  Clock,
  Droplet,
  FlaskConical,
  Pill,
  Plus,
  Target,
  TrendingUp,
  Trash2,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import { Panel, SectionHeader } from "./_shared";
import { adherenceWeeks } from "@/data/patientMock";

/* ---------------- shared mock data ---------------- */

const bgl24h = [
  { t: "00", v: 118 }, { t: "02", v: 105 }, { t: "04", v: 98 },
  { t: "06", v: 112 }, { t: "08", v: 168 }, { t: "10", v: 142 },
  { t: "12", v: 178 }, { t: "14", v: 132 }, { t: "16", v: 124 },
  { t: "18", v: 195 }, { t: "20", v: 156 }, { t: "22", v: 138 },
  { t: "24", v: 145 },
];

const bglRecent = [
  { time: "Today 14:20", value: 145, ctx: "Post-lunch", method: "CGM" },
  { time: "Today 12:05", value: 178, ctx: "Pre-lunch", method: "Fingerstick" },
  { time: "Today 08:30", value: 168, ctx: "Post-breakfast", method: "CGM" },
  { time: "Today 07:00", value: 112, ctx: "Fasting", method: "CGM" },
  { time: "Yest 22:10", value: 138, ctx: "Bedtime", method: "Fingerstick" },
];

const bglColor = (v: number) =>
  v < 70 ? "text-rose-600" : v > 180 ? "text-amber-600" : "text-emerald-600";
const bglBg = (v: number) =>
  v < 70 ? "bg-rose-100/70 border-rose-200/60" :
  v > 180 ? "bg-amber-100/70 border-amber-200/60" :
  "bg-emerald-100/70 border-emerald-200/60";

const activity = [
  { time: "14:20", text: "BGL logged — 145 mg/dL", icon: Droplet },
  { time: "13:00", text: "Metformin 500mg taken", icon: Pill },
  { time: "10:15", text: "Lab result uploaded — HbA1c", icon: FlaskConical },
  { time: "08:30", text: "BGL logged — 168 mg/dL", icon: Droplet },
  { time: "07:00", text: "Glipizide 5mg taken", icon: Pill },
];

/* ---------------- Overview ---------------- */

export const OverviewTab = () => {
  const last = bgl24h[bgl24h.length - 1];
  return (
    <div className="grid grid-cols-3 gap-5">
      <Panel>
        <SectionHeader icon={Droplet} title="Current BGL" />
        <div className={`inline-flex items-baseline gap-2 rounded-2xl border px-4 py-3 ${bglBg(last.v)}`}>
          <span className={`text-[34px] font-semibold tracking-tight ${bglColor(last.v)}`}>{last.v}</span>
          <span className="text-[12px] text-foreground/60">mg/dL</span>
        </div>
        <div className="mt-2 text-[12px] text-foreground/55">2 min ago · CGM · Post-lunch</div>
      </Panel>

      <Panel>
        <SectionHeader icon={Pill} title="Medication" />
        <div className="space-y-2.5">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-foreground/50">Last dose</div>
            <div className="text-[14px] font-medium">Metformin 500mg · 13:00</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-foreground/50">Next dose</div>
            <div className="text-[14px] font-medium">Glipizide 5mg · 19:00</div>
          </div>
        </div>
      </Panel>

      <Panel>
        <SectionHeader icon={AlertTriangle} title="Alerts" />
        <ul className="space-y-2 text-[12.5px]">
          <li className="glass-chip flex items-center gap-2 rounded-2xl px-3 py-2">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            High at 12:05 (178 mg/dL)
          </li>
          <li className="glass-chip flex items-center gap-2 rounded-2xl px-3 py-2">
            <span className="h-2 w-2 rounded-full bg-rose-500" />
            Missed Amaryl evening dose
          </li>
          <li className="glass-chip flex items-center gap-2 rounded-2xl px-3 py-2">
            <span className="h-2 w-2 rounded-full bg-sky-500" />
            HbA1c lab due in 2 weeks
          </li>
        </ul>
      </Panel>

      <Panel className="col-span-2">
        <SectionHeader
          icon={TrendingUp}
          title="BGL — last 24h"
          action={<span className="text-[11.5px] text-foreground/55">Avg 138 · Range 70–180</span>}
        />
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={bgl24h} margin={{ top: 6, right: 6, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="bglFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(165 60% 55%)" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="hsl(165 60% 55%)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" stroke="hsl(220 10% 40%)" fontSize={10} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(220 10% 40%)" fontSize={10} tickLine={false} axisLine={false} width={32} domain={[60, 220]} />
              <Tooltip
                contentStyle={{
                  background: "hsl(0 0% 100% / 0.9)",
                  border: "1px solid hsl(0 0% 100% / 0.6)",
                  borderRadius: 12,
                  backdropFilter: "blur(12px)",
                  fontSize: 12,
                }}
              />
              <Area type="monotone" dataKey="v" stroke="hsl(165 55% 45%)" strokeWidth={2.5} fill="url(#bglFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel>
        <SectionHeader icon={Clock} title="Recent activity" />
        <ul className="space-y-2.5">
          {activity.map((a, i) => (
            <li key={i} className="flex items-start gap-2.5 text-[12.5px]">
              <div className="glass-chip mt-0.5 flex h-7 w-7 items-center justify-center rounded-full">
                <a.icon className="h-3.5 w-3.5 text-foreground/60" />
              </div>
              <div className="flex-1">
                <div className="font-medium">{a.text}</div>
                <div className="text-[11px] text-foreground/50">{a.time}</div>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
};

/* ---------------- BGL Analysis ---------------- */

export const BglAnalysisTab = () => {
  const [range, setRange] = useState<"7" | "14" | "30">("14");
  const stats = useMemo(
    () => ({
      avg: 142,
      tir: 62,
      high: 28,
      low: 10,
    }),
    [range],
  );

  return (
    <div className="space-y-5">
      <Panel>
        <SectionHeader
          icon={TrendingUp}
          title="Trend"
          action={
            <div className="glass-chip flex items-center gap-0.5 rounded-full p-0.5">
              {(["7", "14", "30"] as const).map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={`rounded-full px-3 py-1 text-[11.5px] font-medium transition-colors ${
                    range === r ? "bg-foreground text-background" : "text-foreground/60"
                  }`}
                >
                  {r}d
                </button>
              ))}
            </div>
          }
        />
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Average", value: `${stats.avg}`, unit: "mg/dL" },
            { label: "Time in range", value: `${stats.tir}%`, tone: "text-emerald-600" },
            { label: "High %", value: `${stats.high}%`, tone: "text-amber-600" },
            { label: "Low %", value: `${stats.low}%`, tone: "text-rose-600" },
          ].map((s) => (
            <div key={s.label} className="glass-chip rounded-2xl px-4 py-3">
              <div className={`text-[20px] font-semibold tracking-tight ${s.tone ?? ""}`}>
                {s.value}
                {s.unit && <span className="ml-1 text-[11px] text-foreground/50">{s.unit}</span>}
              </div>
              <div className="text-[11px] text-foreground/55">{s.label}</div>
            </div>
          ))}
        </div>
        <div className="mt-5 h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={bgl24h} margin={{ top: 6, right: 6, left: -16, bottom: 0 }}>
              <XAxis dataKey="t" stroke="hsl(220 10% 40%)" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(220 10% 40%)" fontSize={11} tickLine={false} axisLine={false} width={32} domain={[60, 220]} />
              <Tooltip
                contentStyle={{
                  background: "hsl(0 0% 100% / 0.9)",
                  border: "1px solid hsl(0 0% 100% / 0.6)",
                  borderRadius: 12,
                  backdropFilter: "blur(12px)",
                  fontSize: 12,
                }}
              />
              <Line type="monotone" dataKey="v" stroke="hsl(165 55% 45%)" strokeWidth={2.5} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel>
        <SectionHeader icon={Droplet} title="Recent readings" />
        <div className="grid grid-cols-[1.2fr_0.7fr_1fr_0.7fr] gap-3 border-b border-white/40 pb-2 text-[11px] uppercase tracking-wide text-foreground/50">
          <span>Time</span>
          <span>Value</span>
          <span>Context</span>
          <span>Method</span>
        </div>
        <ul className="divide-y divide-white/40">
          {bglRecent.map((r, i) => (
            <li key={i} className="grid grid-cols-[1.2fr_0.7fr_1fr_0.7fr] items-center gap-3 py-2.5 text-[12.5px]">
              <span className="font-medium">{r.time}</span>
              <span className={`font-semibold ${bglColor(r.value)}`}>{r.value} mg/dL</span>
              <span className="text-foreground/60">{r.ctx}</span>
              <span className="text-foreground/55">{r.method}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
};

/* ---------------- Medications (Overview tab variant) ---------------- */

type SimpleMed = {
  name: string;
  dose: string;
  freq: string;
  next: string;
  refill: "OK" | "Low" | "Out";
};

const initialActiveMeds: SimpleMed[] = [
  { name: "Metformin", dose: "500mg", freq: "Twice daily with meals", next: "Today 19:00", refill: "OK" },
  { name: "Glipizide", dose: "5mg", freq: "Once daily, morning", next: "Tomorrow 08:00", refill: "Low" },
  { name: "Atorvastatin", dose: "20mg", freq: "Once daily, bedtime", next: "Today 22:00", refill: "OK" },
];

const refillTone: Record<SimpleMed["refill"], string> = {
  OK: "bg-emerald-100/70 text-emerald-700 border-emerald-200/60",
  Low: "bg-amber-100/70 text-amber-700 border-amber-200/60",
  Out: "bg-rose-100/70 text-rose-700 border-rose-200/60",
};

export const MedicationsTab = () => {
  const [meds] = useState<SimpleMed[]>(initialActiveMeds);
  return (
    <div className="space-y-5">
      <Panel>
        <SectionHeader
          icon={Pill}
          title="Active medications"
          action={
            <button className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium">
              <Plus className="h-3 w-3" /> Add
            </button>
          }
        />
        <div className="grid grid-cols-[1.4fr_0.8fr_1.4fr_1fr_0.6fr] gap-3 border-b border-white/40 pb-2 text-[11px] uppercase tracking-wide text-foreground/50">
          <span>Name</span>
          <span>Dose</span>
          <span>Frequency</span>
          <span>Next dose</span>
          <span className="text-right">Refill</span>
        </div>
        <ul className="divide-y divide-white/40">
          {meds.map((m, i) => (
            <li key={i} className="grid grid-cols-[1.4fr_0.8fr_1.4fr_1fr_0.6fr] items-center gap-3 py-3 text-[12.5px]">
              <span className="font-medium">{m.name}</span>
              <span>{m.dose}</span>
              <span className="text-foreground/60">{m.freq}</span>
              <span className="text-foreground/60">{m.next}</span>
              <span className={`justify-self-end inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${refillTone[m.refill]}`}>
                {m.refill}
              </span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel>
        <SectionHeader icon={Check} title="Adherence — last 4 weeks" />
        <div className="space-y-1.5">
          {adherenceWeeks.map((week, wi) => (
            <div key={wi} className="flex items-center gap-2">
              <span className="w-12 text-[10.5px] text-foreground/50">W{wi + 1}</span>
              <div className="flex flex-1 gap-1">
                {week.map((d, di) => (
                  <div
                    key={di}
                    className={`h-5 flex-1 rounded ${d ? "bg-emerald-400/70" : "bg-rose-300/70"}`}
                    title={d ? "Taken" : "Missed"}
                  />
                ))}
              </div>
            </div>
          ))}
          <div className="mt-1 flex items-center gap-2">
            <span className="w-12" />
            <div className="flex flex-1 justify-between text-[10px] text-foreground/45">
              {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
                <span key={i} className="flex-1 text-center">{d}</span>
              ))}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
};

/* ---------------- Lab results (MVP) ---------------- */

type Lab = { test: string; value: string; unit: string; ref: string; flag: "Normal" | "High" | "Low"; date: string; goal?: string };

const mvpLabs: Lab[] = [
  { test: "HbA1c", value: "7.8", unit: "%", ref: "<6.5", flag: "High", date: "Apr 2026", goal: "Goal < 7.0%" },
  { test: "eGFR", value: "82", unit: "mL/min", ref: ">60", flag: "Normal", date: "Apr 2026" },
  { test: "LDL", value: "118", unit: "mg/dL", ref: "<100", flag: "High", date: "Mar 2026", goal: "Goal < 100" },
];

const flagTone: Record<Lab["flag"], string> = {
  Normal: "bg-emerald-100/70 text-emerald-700 border-emerald-200/60",
  High: "bg-amber-100/70 text-amber-700 border-amber-200/60",
  Low: "bg-sky-100/70 text-sky-700 border-sky-200/60",
};

export const LabResultsTab = () => (
  <div className="space-y-5">
    <Panel>
      <SectionHeader
        icon={FlaskConical}
        title="Recent labs"
        action={<span className="text-[11.5px] text-foreground/55">Next HbA1c due in 2 weeks</span>}
      />
      <ul className="space-y-2.5">
        {mvpLabs.map((l, i) => (
          <li key={i} className="glass-chip flex items-center justify-between rounded-2xl px-4 py-3">
            <div>
              <div className="text-[13.5px] font-semibold">{l.test}</div>
              <div className="text-[11px] text-foreground/55">
                Ref {l.ref} · {l.date}{l.goal ? ` · ${l.goal}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <div className="text-[18px] font-semibold tracking-tight">
                  {l.value}
                  <span className="ml-1 text-[11px] font-normal text-foreground/50">{l.unit}</span>
                </div>
              </div>
              <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${flagTone[l.flag]}`}>
                {l.flag}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  </div>
);

/* ---------------- Mini Goals ---------------- */

type Goal = { id: string; text: string; target: number; progress: number; due: string; done: boolean };

const initialGoals: Goal[] = [
  { id: "g1", text: "Log BGL before breakfast", target: 5, progress: 3, due: "May 10", done: false },
  { id: "g2", text: "Walk 15 min after dinner", target: 4, progress: 2, due: "May 11", done: false },
  { id: "g3", text: "Take metformin without missing a dose", target: 7, progress: 5, due: "May 12", done: false },
];

const completedGoals = [
  { text: "Log BGL twice daily", date: "Apr 28" },
  { text: "No skipped morning Glipizide", date: "Apr 21" },
];

export const MiniGoalsTab = () => {
  const [goals, setGoals] = useState<Goal[]>(initialGoals);
  const [adding, setAdding] = useState(false);
  const [newText, setNewText] = useState("");
  const [newTarget, setNewTarget] = useState(5);

  const tick = (id: string) => {
    setGoals(goals.map((g) => {
      if (g.id !== id) return g;
      const p = Math.min(g.target, g.progress + 1);
      if (p === g.target && !g.done) toast.success(`Goal achieved: ${g.text}`);
      return { ...g, progress: p, done: p === g.target };
    }));
  };

  const remove = (id: string) => setGoals(goals.filter((g) => g.id !== id));

  const add = () => {
    if (!newText.trim()) return;
    setGoals([...goals, { id: crypto.randomUUID(), text: newText.trim(), target: newTarget, progress: 0, due: "—", done: false }]);
    setNewText("");
    setNewTarget(5);
    setAdding(false);
    toast.success("Goal added");
  };

  return (
    <div className="grid grid-cols-3 gap-5">
      <Panel className="col-span-2">
        <SectionHeader
          icon={Target}
          title="Active goals"
          action={
            <button
              onClick={() => setAdding(true)}
              className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium"
            >
              <Plus className="h-3 w-3" /> Add goal
            </button>
          }
        />
        {adding && (
          <div className="mb-3 rounded-2xl border border-white/50 bg-white/40 p-3 backdrop-blur-md">
            <div className="grid grid-cols-[1fr_120px_auto] gap-2">
              <input
                placeholder="Goal description"
                value={newText}
                onChange={(e) => setNewText(e.target.value)}
                className="glass-chip rounded-xl px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-foreground/20"
              />
              <input
                type="number"
                min={1}
                max={30}
                aria-label="Target days"
                placeholder="Days"
                value={newTarget}
                onChange={(e) => setNewTarget(parseInt(e.target.value) || 1)}
                className="glass-chip rounded-xl px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-foreground/20"
              />
              <button
                onClick={add}
                className="rounded-full bg-foreground px-3 text-[12px] font-medium text-background"
              >
                Save
              </button>
            </div>
          </div>
        )}
        <ul className="space-y-2.5">
          {goals.map((g) => {
            const pct = Math.round((g.progress / g.target) * 100);
            return (
              <li key={g.id} className="glass-chip rounded-2xl px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex-1">
                    <div className="text-[13.5px] font-medium">{g.text}</div>
                    <div className="text-[11px] text-foreground/55">Due {g.due} · {g.progress}/{g.target} days</div>
                  </div>
                  <button
                    onClick={() => tick(g.id)}
                    disabled={g.done}
                    className="glass-chip flex h-7 w-7 items-center justify-center rounded-full disabled:opacity-50"
                    aria-label="Mark progress"
                  >
                    <Check className="h-3.5 w-3.5 text-emerald-700" />
                  </button>
                  <button
                    onClick={() => remove(g.id)}
                    className="glass-chip flex h-7 w-7 items-center justify-center rounded-full"
                    aria-label="Remove"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-rose-600" />
                  </button>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/60">
                  <div
                    className={`h-full rounded-full ${g.done ? "bg-emerald-500" : "bg-foreground/70"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      </Panel>

      <Panel>
        <SectionHeader icon={Activity} title="Completed" />
        <ul className="space-y-2">
          {completedGoals.map((g, i) => (
            <li key={i} className="glass-chip flex items-center justify-between rounded-2xl px-3 py-2 text-[12.5px]">
              <span className="font-medium">{g.text}</span>
              <span className="text-[11px] text-foreground/55">{g.date}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
};
