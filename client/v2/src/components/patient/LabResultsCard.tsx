import { useState } from "react";
import { FlaskConical, Table as TableIcon, TrendingUp } from "lucide-react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Panel, SectionHeader } from "@/components/clinical/_shared";
import { labTrends, type LabRow } from "@/data/patientMock";
import { LabsTable } from "./LabsTable";

type View = "table" | "chart";

export const LabResultsCard = ({
  labs,
  setLabs,
}: {
  labs: LabRow[];
  setLabs: (l: LabRow[]) => void;
}) => {
  const [view, setView] = useState<View>("table");
  const [metric, setMetric] = useState<keyof typeof labTrends>("HbA1c");

  return (
    <Panel className="col-span-2">
      <SectionHeader
        icon={FlaskConical}
        title="Lab results"
        action={
          <div className="glass-chip flex items-center gap-0.5 rounded-full p-0.5">
            <button
              onClick={() => setView("table")}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                view === "table" ? "bg-foreground text-background" : "text-foreground/60"
              }`}
            >
              <TableIcon className="h-3 w-3" /> Table
            </button>
            <button
              onClick={() => setView("chart")}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                view === "chart" ? "bg-foreground text-background" : "text-foreground/60"
              }`}
            >
              <TrendingUp className="h-3 w-3" /> Trend
            </button>
          </div>
        }
      />

      {view === "table" ? (
        <LabsTable labs={labs} setLabs={setLabs} />
      ) : (
        <div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(Object.keys(labTrends) as (keyof typeof labTrends)[]).map((k) => (
              <button
                key={k}
                onClick={() => setMetric(k)}
                className={`rounded-full px-3 py-1 text-[11.5px] font-medium transition-colors ${
                  metric === k
                    ? "bg-foreground text-background"
                    : "glass-chip text-foreground/60"
                }`}
              >
                {k}
              </button>
            ))}
          </div>
          <div className="h-[220px] rounded-2xl border border-white/50 bg-white/30 p-3 backdrop-blur-md">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={labTrends[metric]}>
                <XAxis dataKey="m" stroke="hsl(220 10% 40%)" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="hsl(220 10% 40%)" fontSize={11} tickLine={false} axisLine={false} width={32} />
                <Tooltip
                  contentStyle={{
                    background: "hsl(0 0% 100% / 0.85)",
                    border: "1px solid hsl(0 0% 100% / 0.6)",
                    borderRadius: 12,
                    backdropFilter: "blur(12px)",
                    fontSize: 12,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="v"
                  stroke="hsl(220 80% 55%)"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "hsl(220 80% 55%)" }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </Panel>
  );
};
