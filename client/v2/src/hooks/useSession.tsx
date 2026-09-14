/**
 * useSession — owns the MedScribe session_id lifecycle + segments buffer.
 *
 * The Python backend hands out an opaque `session_id` from
 * POST /api/session/start. That ID is the encounter key for every later
 * call (transcribe, pipeline, upload, record, assistant). It is unrelated
 * to the Supabase auth session — see docs/v2_integration_plan.md.
 *
 * Segments
 * --------
 * The /pipeline endpoint reads `body.segments` (not its own server-side log)
 * to drive the LangGraph run, so we maintain a client-side buffer that
 * Waveform.tsx pushes to after each successful sendTranscription. Timing
 * uses seconds elapsed since session start; estimated duration is text-length
 * based — good enough for the pipeline's ingestion node, which only needs
 * monotonic non-overlapping spans.
 *
 * Lifecycle
 * ---------
 *   - Lazy. A session is created on the first `start()` call.
 *   - One active session at a time. `start()` is idempotent.
 *   - `end()` calls the backend then clears segments + state.
 *   - The component tree must be wrapped in <SessionProvider>.
 */
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import {
  endSession as apiEnd,
  startSession as apiStart,
  type Segment,
  type Speaker,
} from "@/api";

type RecordSegmentInput = {
  speaker: Speaker;
  text: string;
};

type SessionContextValue = {
  sessionId: string | null;
  sessionActive: boolean;
  starting: boolean;
  ending: boolean;
  /** Idempotent: returns the existing session ID if already active. */
  start: () => Promise<string | null>;
  end: () => Promise<void>;

  /** Append a segment for the current speaker; timing is server-relative seconds. */
  recordSegment: (input: RecordSegmentInput) => Segment | null;
  /** Snapshot of segments accumulated since the current session started. */
  getSegments: () => Segment[];
};

const SessionContext = createContext<SessionContextValue | null>(null);

const estimateDurationSec = (text: string): number => {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  // ~2.5 words/second is the rough conversational rate; clamp to [1s, 30s].
  return Math.min(30, Math.max(1, words / 2.5));
};

export const SessionProvider = ({ children }: { children: ReactNode }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);

  // Refs so callers (Waveform's submitUtterance) don't need to memoize.
  const sessionStartRef = useRef<number | null>(null);
  const segmentsRef = useRef<Segment[]>([]);
  const lastEndRef = useRef<number>(0);

  const resetSegments = () => {
    sessionStartRef.current = null;
    segmentsRef.current = [];
    lastEndRef.current = 0;
  };

  const start = useCallback(async () => {
    if (sessionId) return sessionId;
    if (starting) return null;
    setStarting(true);
    try {
      const { session_id } = await apiStart();
      sessionStartRef.current = Date.now();
      segmentsRef.current = [];
      lastEndRef.current = 0;
      setSessionId(session_id);
      return session_id;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Could not start session — ${msg}`);
      return null;
    } finally {
      setStarting(false);
    }
  }, [sessionId, starting]);

  const end = useCallback(async () => {
    if (!sessionId || ending) return;
    setEnding(true);
    try {
      await apiEnd(sessionId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Session end failed — ${msg}`);
    } finally {
      setSessionId(null);
      resetSegments();
      setEnding(false);
    }
  }, [sessionId, ending]);

  const recordSegment = useCallback(
    ({ speaker, text }: RecordSegmentInput): Segment | null => {
      if (!sessionStartRef.current) return null;
      const trimmed = text.trim();
      if (!trimmed) return null;
      const elapsed = (Date.now() - sessionStartRef.current) / 1000;
      const dur = estimateDurationSec(trimmed);
      const start = Math.max(lastEndRef.current, elapsed - dur);
      const end = Math.max(start + dur, elapsed);
      const seg: Segment = {
        start,
        end,
        speaker,
        raw_text: trimmed,
        confidence: 1,
      };
      segmentsRef.current = [...segmentsRef.current, seg];
      lastEndRef.current = end;
      return seg;
    },
    [],
  );

  const getSegments = useCallback(() => segmentsRef.current, []);

  return (
    <SessionContext.Provider
      value={{
        sessionId,
        sessionActive: !!sessionId,
        starting,
        ending,
        start,
        end,
        recordSegment,
        getSegments,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = (): SessionContextValue => {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used inside <SessionProvider>");
  }
  return ctx;
};
