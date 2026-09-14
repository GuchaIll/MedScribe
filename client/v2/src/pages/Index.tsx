import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { LeftRail } from "@/components/clinical/LeftRail";
import { ToolsBar } from "@/components/clinical/ToolsBar";
import { Transcript } from "@/components/clinical/Transcript";
import { Waveform } from "@/components/clinical/Waveform";
import { PipelineProgress } from "@/components/pipeline/PipelineProgress";
import { usePipelineRun } from "@/hooks/usePipelineRun";
import { cn } from "@/lib/utils";

/**
 * The pipeline progress panel auto-opens when a run starts and stays open
 * after completion until dismissed. A small floating chip re-opens it.
 */
const PipelineRunStatus = () => {
  const { nodes, running, result, error } = usePipelineRun();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (running) {
      setOpen(true);
      setCollapsed(false);
    }
  }, [running]);

  const hasOutput = !!(result || error || nodes.length > 0);
  if (!hasOutput && !running) return null;

  return (
    <div className="pointer-events-none absolute right-6 top-6 z-20 flex flex-col items-end gap-2">
      {open ? (
        <PipelineProgress
          nodes={nodes}
          running={running}
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((c) => !c)}
          className="pointer-events-auto"
        />
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={cn(
            "glass-chip pointer-events-auto flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11.5px] font-medium text-foreground/70 backdrop-blur-md hover:text-foreground",
          )}
        >
          <Activity className="h-3 w-3" />
          {running ? "Pipeline running…" : "Pipeline run"}
        </button>
      )}
      {open && !running && (
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="pointer-events-auto text-[10.5px] font-medium text-foreground/50 hover:text-foreground"
        >
          Hide
        </button>
      )}
    </div>
  );
};

const Index = () => {
  return (
    <main className="relative min-h-screen w-full overflow-hidden p-2 md:p-4">
      <div className="pointer-events-none absolute -top-32 -right-20 h-[420px] w-[420px] rounded-full bg-gradient-to-br from-[hsl(38_100%_80%/0.5)] to-transparent blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-gradient-to-tr from-[hsl(220_100%_82%/0.55)] to-transparent blur-3xl" />

      <div className="relative mx-auto flex h-[calc(100vh-1rem)] max-w-[1024px] overflow-hidden rounded-[2.25rem] glass-panel md:h-[calc(100vh-2rem)] xl:max-w-[1480px]">
        <LeftRail />

        <section className="relative flex flex-1 flex-col pl-4 pr-[25px] pb-4 pt-4 md:pl-6 md:pr-[25px] md:pb-6 md:pt-6 lg:pl-8 lg:pr-[25px]">
          <h1 className="sr-only">Clinical Transcription</h1>
          <PipelineRunStatus />
          <div className="flex-1 overflow-hidden">
            <Transcript />
          </div>
          <div className="mt-3 flex flex-col gap-2.5 md:mt-4 md:gap-3">
            <Waveform />
            <ToolsBar />
          </div>
        </section>
      </div>
    </main>
  );
};

export default Index;
