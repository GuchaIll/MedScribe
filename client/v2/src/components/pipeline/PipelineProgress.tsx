/**
 * Live view of the 16-node LangGraph pipeline. Renders as a floating panel
 * anchored to the top-right corner of Index.tsx while a run is in progress.
 *
 * Driven by `usePipelineRun.nodes` (polled every ~500ms during a run) merged
 * over the static catalogue in src/lib/pipelineNodes.ts.
 */
import { useMemo } from "react";
import { Check, ChevronRight, Loader2, X as XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  mergeNodeStatus,
  PHASE_LABELS,
  PHASES,
} from "@/lib/pipelineNodes";
import type {
  PipelineNodeProgress,
  PipelineNodeStatus,
} from "@/api";

const fmtDuration = (ms?: number | null) => {
  if (ms == null) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};

const statusTone = (status: PipelineNodeStatus) => {
  switch (status) {
    case "completed":
      return {
        dotBg: "bg-emerald-100",
        dotBorder: "border-emerald-300",
        dotText: "text-emerald-700",
        label: "text-foreground/75",
        icon: <Check className="h-2.5 w-2.5" strokeWidth={3} />,
        opacity: "opacity-100",
      };
    case "running":
      return {
        dotBg: "bg-sky-100",
        dotBorder: "border-sky-400",
        dotText: "text-sky-700",
        label: "font-semibold text-foreground",
        icon: <Loader2 className="h-2.5 w-2.5 animate-spin" strokeWidth={3} />,
        opacity: "opacity-100",
      };
    case "failed":
      return {
        dotBg: "bg-rose-100",
        dotBorder: "border-rose-400",
        dotText: "text-rose-700",
        label: "text-rose-700",
        icon: <XIcon className="h-2.5 w-2.5" strokeWidth={3} />,
        opacity: "opacity-100",
      };
    case "skipped":
      return {
        dotBg: "bg-transparent",
        dotBorder: "border-foreground/15",
        dotText: "text-foreground/30",
        label: "italic text-foreground/35",
        icon: <span className="text-[8px]">–</span>,
        opacity: "opacity-50",
      };
    default:
      return {
        dotBg: "bg-transparent",
        dotBorder: "border-foreground/15",
        dotText: "text-foreground/30",
        label: "italic text-foreground/40",
        icon: null,
        opacity: "opacity-70",
      };
  }
};

const PhaseHeader = ({
  phase,
  state,
}: {
  phase: keyof typeof PHASE_LABELS;
  state: "done" | "active" | "idle";
}) => (
  <div
    className={cn(
      "mb-1.5 pl-0.5 font-mono text-[8.5px] font-bold uppercase tracking-[0.13em] transition-colors",
      state === "done"
        ? "text-emerald-600"
        : state === "active"
        ? "text-sky-600"
        : "text-foreground/30",
    )}
  >
    {state === "done" ? "✓ " : ""}
    {PHASE_LABELS[phase]}
  </div>
);

const NodeRow = ({ node }: { node: PipelineNodeProgress }) => {
  const tone = statusTone(node.status);
  return (
    <div className={cn("flex items-start gap-2", tone.opacity, "transition-opacity")}>
      <div
        className={cn(
          "mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border",
          tone.dotBg,
          tone.dotBorder,
          tone.dotText,
        )}
      >
        {tone.icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className={cn("truncate font-mono text-[10.5px]", tone.label)}>
          {node.label}
          {node.status === "completed" && node.duration_ms != null && (
            <span className="ml-1.5 font-normal text-foreground/35">
              {fmtDuration(node.duration_ms)}
            </span>
          )}
        </div>
        {node.detail && node.status !== "pending" && (
          <div
            className={cn(
              "truncate font-mono text-[9px]",
              node.status === "failed" ? "text-rose-500" : "text-foreground/40",
            )}
          >
            {node.detail}
          </div>
        )}
      </div>
    </div>
  );
};

export type PipelineProgressProps = {
  nodes: PipelineNodeProgress[];
  running: boolean;
  className?: string;
  /** Render compact (collapsed) variant — phase headers only. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
};

export const PipelineProgress = ({
  nodes,
  running,
  className,
  collapsed,
  onToggleCollapsed,
}: PipelineProgressProps) => {
  const merged = useMemo(() => mergeNodeStatus(nodes), [nodes]);
  const groupedByPhase = useMemo(() => {
    return PHASES.map((phase) => {
      const phaseNodes = merged.filter((n) => n.phase === phase);
      const done = phaseNodes.every(
        (n) => n.status === "completed" || n.status === "skipped",
      );
      const active =
        !done &&
        phaseNodes.some(
          (n) =>
            n.status === "running" ||
            n.status === "completed" ||
            n.status === "failed",
        );
      return { phase, nodes: phaseNodes, done, active };
    });
  }, [merged]);

  const completedCount = merged.filter((n) => n.status === "completed").length;
  const totalCount = merged.length;
  const failed = merged.find((n) => n.status === "failed");

  return (
    <aside
      className={cn(
        "glass-panel pointer-events-auto flex w-[260px] flex-col rounded-2xl bg-white/85 p-3 shadow-[0_12px_28px_-12px_hsl(220_40%_30%/0.25)] backdrop-blur-md",
        className,
      )}
    >
      <header className="mb-2 flex items-center justify-between">
        <div className="min-w-0">
          <div className="font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-foreground/50">
            Pipeline
          </div>
          <div className="mt-0.5 font-mono text-[10px] text-foreground/45">
            {failed
              ? `Failed at ${failed.label}`
              : running
              ? `${completedCount} / ${totalCount} nodes`
              : completedCount > 0
              ? `Completed · ${completedCount}/${totalCount}`
              : "Idle"}
          </div>
        </div>
        {onToggleCollapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand pipeline panel" : "Collapse pipeline panel"}
            className="glass-chip flex h-6 w-6 items-center justify-center rounded-full text-foreground/60 hover:text-foreground"
          >
            <ChevronRight
              className={cn(
                "h-3 w-3 transition-transform",
                collapsed ? "rotate-180" : "rotate-0",
              )}
            />
          </button>
        )}
      </header>

      {!collapsed && (
        <div className="flex flex-col gap-3 overflow-y-auto pr-1">
          {groupedByPhase.map(({ phase, nodes: phaseNodes, done, active }) => (
            <div key={phase}>
              <PhaseHeader
                phase={phase}
                state={done ? "done" : active ? "active" : "idle"}
              />
              <div className="flex flex-col gap-1.5">
                {phaseNodes.map((n) => (
                  <NodeRow key={n.name} node={n} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
};
