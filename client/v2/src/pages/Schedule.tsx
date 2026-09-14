import { Link } from "react-router-dom";
import { ChevronLeft, ChevronDown } from "lucide-react";
import { LeftRail } from "@/components/clinical/LeftRail";

const recents: Record<string, string[]> = {
  Today: ["Follow-up — chest pain workup", "Pre-op consult, R. Alvarez"],
  Yesterday: ["New patient intake — migraines"],
  "Previous 7 days": [
    "Telehealth, hypertension review",
    "Annual physical, J. Lin",
  ],
};

const Schedule = () => {
  return (
    <main className="relative min-h-screen w-full overflow-hidden p-4">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[420px] w-[420px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.5)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.55)] to-transparent blur-3xl" />

      <div className="relative mx-auto flex h-[calc(100vh-2rem)] max-w-[1480px] overflow-hidden rounded-[2.25rem] glass-panel">
        <LeftRail />

        <section className="flex flex-1 flex-col px-10 pb-8 pt-8">
          <header className="mb-6 flex items-center justify-between">
            <Link
              to="/"
              className="glass-chip flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium text-foreground/80 hover:text-foreground"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Back
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Schedule</h1>
            <div className="w-[80px]" />
          </header>

          <div className="flex-1 space-y-6 overflow-y-auto pr-2">
            {Object.entries(recents).map(([group, items]) => (
              <div key={group}>
                <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground">
                  <span>{group}</span>
                  <ChevronDown className="h-3.5 w-3.5" />
                </div>
                <ul className="flex flex-col gap-2">
                  {items.map((t) => (
                    <li
                      key={t}
                      className="glass-chip cursor-pointer rounded-2xl px-4 py-3 text-[14px] text-foreground/80 transition-colors hover:text-foreground"
                    >
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
};

export default Schedule;
