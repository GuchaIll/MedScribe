import { Clock, Coffee, CupSoda, Flame, Moon, Plus, Snowflake, Utensils } from "lucide-react";
import { Panel, SectionHeader } from "@/components/clinical/_shared";

const intakes = [
  { icon: CupSoda, label: "8 Cups", sub: "- per day" },
  { icon: Coffee, label: "3 Cups", sub: "- per day" },
];

const habits = [
  { icon: Clock, text: "Intermittent fasting, Intermittent fasting," },
  { icon: Flame, text: "Table sugar , Daily Avg 3 / 6" },
  { icon: Snowflake, text: "Lactose, Beans" },
  { icon: Moon, text: "8 H (continues) sleeping" },
];

export const DietPanel = () => (
  <Panel>
    <SectionHeader
      icon={Utensils}
      title="Diet"
      action={
        <button className="glass-chip flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium">
          <Plus className="h-3 w-3" /> Notes
        </button>
      }
    />
    <div className="grid grid-cols-2 gap-2.5">
      {intakes.map((d) => (
        <div key={d.label} className="glass-chip flex items-center gap-2 rounded-2xl px-3 py-2.5">
          <d.icon className="h-4 w-4 text-foreground/60" />
          <div className="text-[12.5px]">
            <span className="font-semibold">{d.label}</span>
            <span className="text-foreground/50"> {d.sub}</span>
          </div>
        </div>
      ))}
    </div>
    <ul className="mt-3 space-y-2">
      {habits.map((d, i) => (
        <li key={i} className="glass-chip flex items-center gap-2.5 rounded-2xl px-3 py-2.5 text-[12.5px]">
          <d.icon className="h-4 w-4 text-foreground/60" />
          <span>{d.text}</span>
        </li>
      ))}
    </ul>
  </Panel>
);
