import { ReactNode, ComponentType, SVGProps } from "react";

type IconType = ComponentType<SVGProps<SVGSVGElement>>;

export const Panel = ({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) => (
  <div className={`glass-panel rounded-[1.75rem] p-6 ${className}`}>{children}</div>
);

export const SectionHeader = ({
  icon: Icon,
  title,
  action,
}: {
  icon: IconType;
  title: string;
  action?: ReactNode;
}) => (
  <div className="mb-5 flex items-center justify-between">
    <div className="flex items-center gap-2.5">
      <div className="glass-chip flex h-8 w-8 items-center justify-center rounded-xl">
        <Icon className="h-4 w-4 text-foreground/70" strokeWidth={1.8} />
      </div>
      <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
    </div>
    {action}
  </div>
);

export type Tone = "emerald" | "amber" | "rose" | "sky";

export const toneClasses: Record<Tone, string> = {
  emerald: "bg-emerald-100/70 text-emerald-700 border-emerald-200/60",
  amber: "bg-amber-100/70 text-amber-700 border-amber-200/60",
  rose: "bg-rose-100/70 text-rose-700 border-rose-200/60",
  sky: "bg-sky-100/70 text-sky-700 border-sky-200/60",
};
