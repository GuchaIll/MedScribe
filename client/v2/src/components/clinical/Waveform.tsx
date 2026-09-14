import { useEffect, useRef, useState } from "react";
import { AudioLines, Type, SendHorizonal, Crosshair, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { transcriptStore } from "./transcriptStore";
import { useSession } from "@/hooks/useSession";
import { useVoiceCapture } from "@/hooks/useVoiceCapture";
import { sendTranscription, uploadAudioSegment } from "@/api";
import { float32ToWavBlob } from "@/lib/audio";

const BAR_COUNT = 72;
const CAL_KEY = "waveform.peakBaseline";
const GATE_KEY = "waveform.noiseGate";

type Mode = "text" | "audio";

export const Waveform = () => {
  const { sessionId, start: startSession, recordSegment } = useSession();
  const sessionRef = useRef(sessionId);
  useEffect(() => {
    sessionRef.current = sessionId;
  }, [sessionId]);

  const [mode, setMode] = useState<Mode>("audio");
  const [text, setText] = useState("");
  const [levels, setLevels] = useState<number[]>(() => Array(BAR_COUNT).fill(0.12));
  const [elapsed, setElapsed] = useState(0);
  const [calibrating, setCalibrating] = useState(false);
  const [peakBaseline, setPeakBaseline] = useState<number>(() => {
    const v = parseFloat(localStorage.getItem(CAL_KEY) || "");
    return Number.isFinite(v) && v > 0 ? v : 200;
  });
  const [noiseGate, setNoiseGate] = useState<number>(() => {
    const v = parseFloat(localStorage.getItem(GATE_KEY) || "");
    return Number.isFinite(v) ? v : 0.08;
  });
  const peakBaselineRef = useRef(peakBaseline);
  const noiseGateRef = useRef(noiseGate);
  const calibrationRef = useRef<{ active: boolean; max: number; until: number }>({
    active: false,
    max: 0,
    until: 0,
  });
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | undefined>(undefined);
  const startRef = useRef<number>(Date.now());

  /* -- Real transcription wiring ------------------------------------------ */

  const submitUtterance = async (
    utterance: string,
    speaker: "Patient" | "Clinician",
  ) => {
    let id = sessionRef.current;
    if (!id) id = await startSession();
    if (!id) return;
    // Optimistic render so the UI feels live while the backend echoes back.
    const optimistic = transcriptStore.addTurn({
      speaker,
      text: utterance,
      kind: "message",
      partial: true,
    });
    try {
      const res = await sendTranscription(id, utterance, speaker);
      const finalText = res.transcription || utterance;
      transcriptStore.updateTurn(optimistic.id, finalText);
      // Snapshot for the pipeline — see useSession::recordSegment.
      recordSegment({ speaker, text: finalText });
      if (res.agent_message) {
        transcriptStore.addTurn({
          speaker: "Scribe",
          text: res.agent_message,
          kind: "message",
        });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Transcription rejected — ${msg}`);
    }
  };

  const voice = useVoiceCapture({
    enabled: mode === "audio",
    onUtterance: (t) => void submitUtterance(t, "Patient"),
    onAudioSegment: async (audio) => {
      let id = sessionRef.current;
      if (!id) id = await startSession();
      if (!id) return;

      const now = Date.now();
      const sampleRateHz = 16000;
      const durationMs = Math.max(1, Math.round((audio.length / sampleRateHz) * 1000));
      const segmentId = crypto.randomUUID();

      try {
        await uploadAudioSegment(id, {
          segment_id: segmentId,
          started_at_ms: now - durationMs,
          ended_at_ms: now,
          sample_rate_hz: sampleRateHz,
          mime_type: "audio/wav",
          optimistic_speaker: "Patient",
          file: float32ToWavBlob(audio, sampleRateHz),
          file_name: `${segmentId}.wav`,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(`Audio segment upload failed — ${msg}`);
      }
    },
    onError: (m) => toast.error(m),
  });

  /* -- Visualisation: AnalyserNode → SVG levels --------------------------- */

  useEffect(() => {
    peakBaselineRef.current = peakBaseline;
    localStorage.setItem(CAL_KEY, String(peakBaseline));
  }, [peakBaseline]);
  useEffect(() => {
    noiseGateRef.current = noiseGate;
    localStorage.setItem(GATE_KEY, String(noiseGate));
  }, [noiseGate]);

  useEffect(() => {
    if (mode !== "audio") return;
    let cancelled = false;

    const start = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const ctx = new (window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext)();
        audioCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        analyserRef.current = analyser;
        loop();
      } catch {
        simulate();
      }
    };

    const loop = () => {
      const analyser = analyserRef.current;
      if (!analyser) return;
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      const step = Math.floor(data.length / BAR_COUNT);
      let frameMax = 0;
      const baseline = peakBaselineRef.current;
      const gate = noiseGateRef.current;
      const next = Array.from({ length: BAR_COUNT }, (_, i) => {
        const raw = data[i * step] ?? 0;
        if (raw > frameMax) frameMax = raw;
        let norm = raw / baseline;
        if (norm < gate) norm = 0.06;
        else norm = 0.06 + (norm - gate) * (1 / (1 - gate));
        return Math.max(0.06, Math.min(1, norm));
      });
      const cal = calibrationRef.current;
      if (cal.active) {
        if (frameMax > cal.max) cal.max = frameMax;
        if (Date.now() > cal.until) {
          cal.active = false;
          const newBaseline = Math.max(40, cal.max * 0.85);
          setPeakBaseline(newBaseline);
          setCalibrating(false);
          toast.success(`Calibrated · peak baseline ${Math.round(newBaseline)}`);
        }
      }
      setLevels(next);
      rafRef.current = requestAnimationFrame(loop);
    };

    const simulate = () => {
      const tick = () => {
        const t = Date.now() / 200;
        const gate = noiseGateRef.current;
        const next = Array.from({ length: BAR_COUNT }, (_, i) => {
          const base = Math.abs(Math.sin(i * 0.25 + t));
          const noise = Math.random() * 0.4;
          const env = Math.sin((i / BAR_COUNT) * Math.PI);
          let v = base * 0.55 + noise * env;
          if (v < gate) v = 0.06;
          else v = 0.06 + (v - gate) * (1 / (1 - gate));
          return Math.max(0.08, Math.min(1, v));
        });
        const cal = calibrationRef.current;
        if (cal.active && Date.now() > cal.until) {
          cal.active = false;
          setCalibrating(false);
          toast.success("Calibrated (simulated input)");
        }
        setLevels(next);
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    };

    start();
    startRef.current = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)),
      1000,
    );

    return () => {
      cancelled = true;
      clearInterval(timer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close();
      streamRef.current = null;
      audioCtxRef.current = null;
      analyserRef.current = null;
    };
  }, [mode]);

  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  const toggleMode = () => setMode((m) => (m === "audio" ? "text" : "audio"));

  const startCalibration = () => {
    if (mode !== "audio") return;
    calibrationRef.current = { active: true, max: 0, until: Date.now() + 2500 };
    setCalibrating(true);
    toast("Calibrating… speak normally for 2 seconds");
  };

  /* Multistroke ribbon waveform — strongest amplitude in the middle, fading at edges */
  const W = 600;
  const H = 90;
  const mid = H / 2;
  const STROKES = 18;

  const sorted = [...levels].sort((a, b) => a - b);
  const arranged: number[] = new Array(levels.length);
  for (let i = 0; i < sorted.length; i++) {
    const target =
      i % 2 === 0
        ? Math.floor(levels.length / 2) + Math.floor(i / 2)
        : Math.floor(levels.length / 2) - Math.ceil(i / 2);
    arranged[target] = sorted[sorted.length - 1 - i];
  }

  const buildPath = (phase: number, ampScale: number) => {
    const step = W / (arranged.length - 1);
    const pts = arranged.map((v, i) => {
      const x = i * step;
      const norm = (i - (arranged.length - 1) / 2) / ((arranged.length - 1) / 2);
      const env = Math.exp(-norm * norm * 3.2);
      const wave =
        Math.sin((i / arranged.length) * Math.PI * 6 + phase) * 0.55 +
        Math.sin((i / arranged.length) * Math.PI * 14 + phase * 1.7) * 0.25;
      const y = mid + wave * v * env * ampScale * (H / 2 - 22);
      return [x, y] as const;
    });
    let d = `M ${pts[0][0]} ${pts[0][1]}`;
    for (let i = 1; i < pts.length; i++) {
      const [px, py] = pts[i - 1];
      const [x, y] = pts[i];
      const cx = (px + x) / 2;
      d += ` Q ${px} ${py} ${cx} ${(py + y) / 2}`;
    }
    return d;
  };

  const statusLabel = voice.userSpeaking
    ? "Listening"
    : voice.vadLoading
    ? "Loading VAD"
    : voice.vadErrored
    ? "Basic mode"
    : voice.supported
    ? "Idle"
    : "Mic unsupported";

  return (
    <div className="relative w-full">
      <div
        className={cn(
          "relative flex w-full items-center gap-3 transition-colors",
          mode === "audio" ? "p-2 pl-2" : "glass-panel rounded-full p-2 pl-2",
        )}
        style={
          mode === "audio"
            ? {
                background:
                  "linear-gradient(90deg, transparent 0%, hsl(240 4% 48% / 0.55) 18%, #727282 50%, hsl(240 4% 48% / 0.55) 82%, transparent 100%)",
              }
            : undefined
        }
      >
        <button
          type="button"
          onClick={toggleMode}
          aria-label={mode === "audio" ? "Switch to text" : "Switch to audio"}
          className={cn(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-all",
            mode === "audio"
              ? "bg-white/10 text-white backdrop-blur-xl hover:bg-white/20"
              : "glass-chip text-foreground/70 hover:text-foreground",
          )}
        >
          {mode === "audio" ? (
            <Type className="h-[18px] w-[18px]" strokeWidth={2} />
          ) : (
            <AudioLines className="h-[18px] w-[18px]" strokeWidth={2} />
          )}
        </button>

        {mode === "audio" ? (
          <>
            <div
              className="relative flex h-10 flex-1 items-center overflow-hidden px-4"
              style={{
                WebkitMaskImage:
                  "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.35) 12%, black 38%, black 62%, rgba(0,0,0,0.35) 88%, transparent 100%)",
                maskImage:
                  "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.35) 12%, black 38%, black 62%, rgba(0,0,0,0.35) 88%, transparent 100%)",
              }}
            >
              <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
                <defs>
                  <linearGradient id="wave-rainbow" x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0%" stopColor="hsl(0 95% 60%)" stopOpacity="0" />
                    <stop offset="8%" stopColor="hsl(15 95% 60%)" stopOpacity="0.9" />
                    <stop offset="22%" stopColor="hsl(40 100% 60%)" stopOpacity="1" />
                    <stop offset="40%" stopColor="hsl(135 90% 55%)" stopOpacity="1" />
                    <stop offset="58%" stopColor="hsl(160 90% 55%)" stopOpacity="1" />
                    <stop offset="76%" stopColor="hsl(195 95% 60%)" stopOpacity="1" />
                    <stop offset="92%" stopColor="hsl(225 95% 65%)" stopOpacity="0.9" />
                    <stop offset="100%" stopColor="hsl(235 95% 65%)" stopOpacity="0" />
                  </linearGradient>
                  <filter id="wave-glow" x="-20%" y="-50%" width="140%" height="200%">
                    <feGaussianBlur stdDeviation="1.2" />
                  </filter>
                  <mask id="wave-edge-fade">
                    <linearGradient id="edge-fade-x" x1="0" x2="1" y1="0" y2="0">
                      <stop offset="0%" stopColor="white" stopOpacity="0" />
                      <stop offset="18%" stopColor="white" stopOpacity="1" />
                      <stop offset="82%" stopColor="white" stopOpacity="1" />
                      <stop offset="100%" stopColor="white" stopOpacity="0" />
                    </linearGradient>
                    <rect width={W} height={H} fill="url(#edge-fade-x)" />
                  </mask>
                </defs>
                <g mask="url(#wave-edge-fade)" filter="url(#wave-glow)">
                  {Array.from({ length: STROKES }).map((_, i) => {
                    const t = i / (STROKES - 1);
                    const phase = t * Math.PI * 1.6;
                    const ampScale = 0.35 + t * 0.95;
                    const opacity = 0.35 + (1 - Math.abs(t - 0.5) * 2) * 0.55;
                    return (
                      <path
                        key={i}
                        d={buildPath(phase, ampScale)}
                        fill="none"
                        stroke="url(#wave-rainbow)"
                        strokeWidth={0.9}
                        strokeOpacity={opacity}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    );
                  })}
                </g>
              </svg>
            </div>

            <div className="flex items-center gap-3 pr-3 font-mono text-sm tabular-nums text-white/90">
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    title="Audio tuning"
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-white backdrop-blur-xl transition-all hover:bg-white/20"
                  >
                    <Settings2 className="h-3.5 w-3.5" />
                  </button>
                </PopoverTrigger>
                <PopoverContent
                  align="end"
                  sideOffset={10}
                  className="w-64 rounded-2xl border-white/20 bg-[#727282] p-4 text-white shadow-[0_10px_30px_-10px_hsl(0_0%_0%/0.55)] backdrop-blur-xl"
                >
                  <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-white/70">
                    Audio tuning
                  </div>
                  <div className="mb-4">
                    <div className="mb-1.5 flex items-center justify-between text-[11px] uppercase tracking-wider text-white/70">
                      <span>Noise gate</span>
                      <span className="font-mono text-white/60">{noiseGate.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={0.6}
                      step={0.01}
                      aria-label="Noise gate"
                      value={noiseGate}
                      onChange={(e) => setNoiseGate(parseFloat(e.target.value))}
                      className="h-1 w-full cursor-pointer accent-white/90"
                    />
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-[11px] uppercase tracking-wider text-white/70">
                      <span>Peak baseline</span>
                      <span className="font-mono text-white/60">{Math.round(peakBaseline)}</span>
                    </div>
                    <button
                      type="button"
                      onClick={startCalibration}
                      disabled={calibrating}
                      className={cn(
                        "flex w-full items-center justify-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-[11px] uppercase tracking-wider text-white transition-all hover:bg-white/20",
                        calibrating && "animate-pulse",
                      )}
                    >
                      <Crosshair className="h-3 w-3" />
                      {calibrating ? "Calibrating…" : "Calibrate"}
                    </button>
                  </div>
                </PopoverContent>
              </Popover>
              <span
                className={cn(
                  "h-2 w-2 rounded-full transition-all",
                  voice.userSpeaking
                    ? "bg-white shadow-[0_0_10px_2px_hsl(0_0%_100%/0.8)] animate-pulse-dot"
                    : "bg-white/40",
                )}
              />
              <span className="text-[11px] uppercase tracking-wider opacity-80">
                {statusLabel}
              </span>
              <span className="ml-1">
                {mm}:{ss}
              </span>
            </div>
          </>
        ) : (
          <>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && text.trim()) {
                  void submitUtterance(text.trim(), "Clinician");
                  setText("");
                }
              }}
              placeholder="Type a note or instruction…"
              className="flex h-11 flex-1 bg-transparent px-3 text-[14px] text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
            <button
              type="button"
              aria-label="Send"
              onClick={() => {
                if (!text.trim()) return;
                void submitUtterance(text.trim(), "Clinician");
                setText("");
              }}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-[0_8px_20px_-6px_hsl(var(--primary)/0.5)] transition-transform hover:scale-105"
            >
              <SendHorizonal className="h-[18px] w-[18px]" />
            </button>
          </>
        )}
      </div>
    </div>
  );
};
