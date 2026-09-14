import { Link } from "react-router-dom";
import { Bell, ChevronDown, ChevronLeft, Search } from "lucide-react";

export const PatientTopBar = () => (
  <header className="flex items-center gap-4">
    <Link
      to="/"
      className="glass-chip flex h-9 w-9 items-center justify-center rounded-full text-foreground/70 hover:text-foreground"
      aria-label="Back"
    >
      <ChevronLeft className="h-4 w-4" />
    </Link>
    <div className="flex items-baseline gap-2">
      <h1 className="text-[22px] font-semibold tracking-tight">Ahmed Ali</h1>
      <span className="text-[15px] font-medium text-emerald-600">[ Type 2 ]</span>
    </div>

    <div className="glass-chip mx-6 flex h-10 flex-1 items-center gap-3 rounded-full px-4">
      <Search className="h-4 w-4 text-foreground/40" />
      <input
        placeholder="Search ..."
        className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-foreground/40"
      />
    </div>

    <button className="glass-chip flex h-10 w-10 items-center justify-center rounded-full" aria-label="Notifications">
      <Bell className="h-4 w-4 text-foreground/70" />
    </button>

    <div className="glass-chip flex items-center gap-2.5 rounded-full py-1 pl-1 pr-3">
      <div className="h-8 w-8 rounded-full bg-gradient-to-br from-[hsl(220_60%_70%)] to-[hsl(280_60%_70%)]" />
      <div className="leading-tight">
        <div className="text-[13px] font-semibold">Ahmed Kamal</div>
        <div className="text-[11px] text-foreground/50">Doctor</div>
      </div>
      <ChevronDown className="h-3.5 w-3.5 text-foreground/50" />
    </div>
  </header>
);

export const PatientTabsNav = ({
  tabs,
  activeTab,
  onSelect,
}: {
  tabs: readonly string[];
  activeTab: number;
  onSelect: (i: number) => void;
}) => (
  <nav className="flex items-center gap-7 border-b border-white/40 px-1">
    {tabs.map((t, i) => {
      const active = i === activeTab;
      return (
        <button
          key={t}
          onClick={() => onSelect(i)}
          className={`relative pb-3 text-[13.5px] transition-colors ${
            active ? "font-semibold text-foreground" : "text-foreground/55 hover:text-foreground"
          }`}
        >
          {t}
          {active && (
            <span className="absolute -bottom-px left-0 right-0 h-[2px] rounded-full bg-foreground" />
          )}
        </button>
      );
    })}
  </nav>
);
