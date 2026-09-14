/**
 * usePipelineRun — orchestrates a LangGraph pipeline invocation.
 *
 * Lifecycle:
 *   1. ToolsBar (or any consumer) calls `run({ patientId, doctorId })`.
 *   2. We pull the accumulated transcript segments from SessionContext,
 *      POST them to /api/session/{id}/pipeline, and start polling
 *      /pipeline/status every ~500ms for live node progress.
 *   3. While running, PipelineProgress reads `nodes` to render the
 *      16-node ladder.
 *   4. On terminal status (completed | failed) we stop polling and:
 *        - append the returned `clinical_note` as a Scribe SOAP bubble
 *        - if `validation_report.needs_review` is true, append a
 *          ReviewChangesCard bubble built from the structured_record
 *
 * State is provider-scoped so PipelineProgress and ToolsBar share it.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import {
  getPipelineStatus,
  runPipeline as apiRunPipeline,
  type PipelineNodeProgress,
  type PipelineProgress,
  type RunPipelineResponse,
} from "@/api";
import { useSession } from "@/hooks/useSession";
import { transcriptStore } from "@/components/clinical/transcriptStore";
import {
  buildReviewFields,
  type ValidationReport,
} from "@/lib/pipelineReview";

type RunOptions = {
  /** Defaults to a demo doctor when omitted; Phase 5 will wire real IDs. */
  patientId?: string;
  doctorId?: string;
};

type PipelineRunContextValue = {
  running: boolean;
  nodes: PipelineNodeProgress[];
  result: RunPipelineResponse | null;
  error: string | null;
  run: (opts?: RunOptions) => Promise<RunPipelineResponse | null>;
  reset: () => void;
};

const PipelineRunContext = createContext<PipelineRunContextValue | null>(null);

const POLL_MS = 500;
const TERMINAL_WAIT_MS = 45_000;
const TERMINAL = new Set(["completed", "failed"]);

const DEFAULT_PATIENT_ID = "patient-default-001";
const DEFAULT_DOCTOR_ID = "doctor-default-001";

const fmtSoapTitle = (sessionId: string | null) =>
  sessionId
    ? `SOAP NOTE — Session ${sessionId.slice(0, 8)}`
    : "SOAP NOTE";

const summarizePipelineFailure = (err: unknown): string =>
  err instanceof Error ? err.message : String(err);

export const PipelineRunProvider = ({ children }: { children: ReactNode }) => {
  const { sessionId, start: startSession, getSegments } = useSession();
  const [running, setRunning] = useState(false);
  const [nodes, setNodes] = useState<PipelineNodeProgress[]>([]);
  const [result, setResult] = useState<RunPipelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollHandleRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPoll = useCallback(() => {
    if (pollHandleRef.current) {
      clearInterval(pollHandleRef.current);
      pollHandleRef.current = null;
    }
  }, []);
  useEffect(() => stopPoll, [stopPoll]);

  const reset = useCallback(() => {
    setRunning(false);
    setNodes([]);
    setResult(null);
    setError(null);
    stopPoll();
  }, [stopPoll]);

  const startPolling = useCallback(
    (id: string) => {
      stopPoll();
      pollHandleRef.current = setInterval(async () => {
        try {
          const status = await getPipelineStatus(id);
          setNodes(status.nodes ?? []);
          if (TERMINAL.has(status.status)) {
            stopPoll();
          }
        } catch (err) {
          // Status-poll failures are non-fatal; the main runPipeline promise
          // will surface the real error.
          console.warn("Pipeline status poll failed:", err);
        }
      }, POLL_MS);
    },
    [stopPoll],
  );

  const waitForTerminalStatus = useCallback(
    async (id: string): Promise<PipelineProgress> => {
      const deadline = Date.now() + TERMINAL_WAIT_MS;
      while (Date.now() < deadline) {
        const status = await getPipelineStatus(id);
        setNodes(status.nodes ?? []);
        if (TERMINAL.has(status.status)) {
          return status;
        }
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
      }
      throw new Error("Pipeline timed out before producing a completed result");
    },
    [],
  );

  const statusToResult = useCallback(
    (status: PipelineProgress, id: string): RunPipelineResponse => ({
      session_id: status.session_id || id,
      clinical_note: status.clinical_note ?? undefined,
      structured_record: status.structured_record ?? undefined,
      clinical_suggestions: status.clinical_suggestions ?? undefined,
      validation_report: status.validation_report ?? undefined,
      message: status.message ?? undefined,
    }),
    [],
  );

  const emitOutputBubbles = useCallback(
    (res: RunPipelineResponse) => {
      // 1. The SOAP note bubble (uses the existing kind:"soap" renderer).
      if (res.clinical_note) {
        const title = fmtSoapTitle(res.session_id);
        const body =
          res.clinical_note.startsWith(title) || res.clinical_note.startsWith("SOAP")
            ? res.clinical_note
            : `${title}\n\n${res.clinical_note}`;
        transcriptStore.addTurn({
          speaker: "Scribe",
          kind: "soap",
          text: body,
        });
      }

      // 2. The review-changes card, when the pipeline asks for human review.
      const validation = (res.validation_report ?? {}) as ValidationReport;
      const needsReview = validation.needs_review === true;
      if (needsReview && res.structured_record) {
        const fields = buildReviewFields(res.structured_record, validation);
        transcriptStore.addTurn({
          speaker: "Scribe",
          kind: "review_changes",
          text:
            "Pipeline completed — please review the changes below before persisting to the patient record.",
          reviewChanges: { fields, approved: false },
        });
      }
    },
    [],
  );

  const run = useCallback(
    async (opts?: RunOptions): Promise<RunPipelineResponse | null> => {
      if (running) return null;

      const id = sessionId ?? (await startSession());
      if (!id) {
        toast.error("No active session — cannot run pipeline");
        return null;
      }
      const segments = getSegments();
      if (segments.length === 0) {
        toast.error("No transcript segments yet — speak or type something first");
        return null;
      }

      setRunning(true);
      setError(null);
      setNodes([]);
      setResult(null);
      const placeholder = transcriptStore.addTurn({
        speaker: "Scribe",
        kind: "message",
        text: "Running clinical pipeline…",
        partial: true,
      });

      startPolling(id);

      try {
        await apiRunPipeline(
          id,
          opts?.patientId ?? DEFAULT_PATIENT_ID,
          opts?.doctorId ?? DEFAULT_DOCTOR_ID,
          segments,
        );

        const terminalStatus = await waitForTerminalStatus(id);
        if (terminalStatus.status === "failed") {
          throw new Error(
            terminalStatus.error ||
              terminalStatus.message ||
              "Pipeline failed before producing a result",
          );
        }
        const res = statusToResult(terminalStatus, id);
        setResult(res);

        transcriptStore.updateTurn(
          placeholder.id,
          res.clinical_note
            ? "Pipeline completed — SOAP note generated."
            : "Pipeline completed.",
        );
        transcriptStore.patchTurn(placeholder.id, { partial: false });
        emitOutputBubbles(res);
        toast.success("Pipeline complete — review changes below");
        return res;
      } catch (err) {
        const msg = summarizePipelineFailure(err);
        setError(msg);
        transcriptStore.updateTurn(placeholder.id, `Pipeline failed — ${msg}`);
        transcriptStore.patchTurn(placeholder.id, { partial: false });
        toast.error(`Pipeline failed — ${msg}`);
        return null;
      } finally {
        setRunning(false);
        stopPoll();
      }
    },
    [
      running,
      sessionId,
      startSession,
      getSegments,
      startPolling,
      emitOutputBubbles,
      stopPoll,
      waitForTerminalStatus,
      statusToResult,
    ],
  );

  return (
    <PipelineRunContext.Provider value={{ running, nodes, result, error, run, reset }}>
      {children}
    </PipelineRunContext.Provider>
  );
};

export const usePipelineRun = (): PipelineRunContextValue => {
  const ctx = useContext(PipelineRunContext);
  if (!ctx) {
    throw new Error("usePipelineRun must be used inside <PipelineRunProvider>");
  }
  return ctx;
};
