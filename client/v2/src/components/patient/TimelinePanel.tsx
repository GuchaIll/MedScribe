import { CalendarDays } from "lucide-react";
import { Panel, SectionHeader } from "@/components/clinical/_shared";
import { timeline } from "@/data/patientMock";

export const TimelinePanel = () => (
  <Panel>
    <SectionHeader icon={CalendarDays} title="Timeline" />
    <ul className="space-y-4">
      {timeline.map((t, i) => (
        <li key={i} className="flex gap-4">
          <div className="w-12 shrink-0 text-[11px] font-medium uppercase text-foreground/50">
            {t.date}
          </div>
          <div className="relative flex flex-col items-center">
            <span className="mt-1 h-2.5 w-2.5 rounded-full border-2 border-sky-500 bg-white" />
            {i < timeline.length - 1 && <span className="mt-1 h-8 w-px bg-foreground/15" />}
          </div>
          <div>
            <div className="text-[13.5px] font-medium">{t.title}</div>
            {t.a1c && <div className="text-[11.5px] text-foreground/50">A1c : {t.a1c}</div>}
          </div>
        </li>
      ))}
    </ul>
  </Panel>
);
