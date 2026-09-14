/**
 * useVoiceCapture — VAD-enhanced speech recognition.
 *
 * Combines `@ricky0123/vad-web` (Silero VAD) loaded from CDN via `window.vad`
 * with `react-speech-recognition` (Web Speech API).
 *
 * - When VAD fires `onSpeechStart`, Web Speech API starts immediately.
 * - When VAD fires `onSpeechEnd`, the last final transcript is committed.
 * - If VAD fails to load (CDN blocked, etc.) we fall back to a silence-timer
 *   on top of plain continuous Web Speech API.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";

/* -- Minimal types for the CDN-loaded MicVAD global -- */
type MicVADInstance = {
  start: () => void;
  pause: () => void;
  destroy?: () => void;
};

type MicVADOptions = {
  onSpeechStart?: () => void;
  onSpeechEnd?: (audio: Float32Array) => void;
  positiveSpeechThreshold?: number;
  negativeSpeechThreshold?: number;
  redemptionFrames?: number;
  preSpeechPadFrames?: number;
  minSpeechFrames?: number;
  onnxWASMBasePath?: string;
  baseAssetPath?: string;
  startOnLoad?: boolean;
};

type MicVADCtor = { new: (opts: MicVADOptions) => Promise<MicVADInstance> };

declare global {
  interface Window {
    vad?: { MicVAD?: MicVADCtor };
  }
}

export type UseVoiceCaptureOptions = {
  /** Whether capture is active. */
  enabled?: boolean;
  /** Soft-mute: keep mic open but ignore final transcripts. */
  muted?: boolean;
  /** Called with `text` when an utterance ends. */
  onUtterance?: (text: string) => void;
  /** Called with raw voiced audio when VAD closes an utterance. */
  onAudioSegment?: (audio: Float32Array) => void | Promise<void>;
  /** Called with a human-readable message when something goes wrong. */
  onError?: (message: string) => void;
  /** Fallback silence window (ms) when VAD isn't available. */
  silenceMs?: number;
};

export function useVoiceCapture({
  enabled = false,
  muted = false,
  onUtterance,
  onAudioSegment,
  onError,
  silenceMs = 2500,
}: UseVoiceCaptureOptions) {
  const {
    transcript,
    interimTranscript,
    finalTranscript,
    resetTranscript,
    listening,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  const onUtteranceRef = useRef(onUtterance);
  const onAudioSegmentRef = useRef(onAudioSegment);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onUtteranceRef.current = onUtterance;
  }, [onUtterance]);
  useEffect(() => {
    onAudioSegmentRef.current = onAudioSegment;
  }, [onAudioSegment]);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const lastFinal = useRef("");
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const vadRef = useRef<MicVADInstance | null>(null);
  const [vadReady, setVadReady] = useState(false);
  const [vadLoading, setVadLoading] = useState(false);
  const [vadErrored, setVadErrored] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);

  const commitPhrase = useCallback(() => {
    if (muted) return;
    const text = lastFinal.current.trim();
    if (text && onUtteranceRef.current) onUtteranceRef.current(text);
    lastFinal.current = "";
    resetTranscript();
  }, [muted, resetTranscript]);

  /* Initialise VAD from the CDN global exactly once. */
  useEffect(() => {
    if (typeof window === "undefined" || !window.vad?.MicVAD) {
      console.warn(
        "[VAD] window.vad not found — CDN scripts may not have loaded.\n" +
          "  Ensure index.html includes ort.wasm.min.js and bundle.min.js before </body>.\n" +
          "  Falling back to plain Web Speech API.",
      );
      setVadErrored(true);
      return;
    }

    let cancelled = false;
    setVadLoading(true);

    window.vad.MicVAD.new({
      onSpeechStart: () => {
        if (cancelled) return;
        setUserSpeaking(true);
        if (browserSupportsSpeechRecognition) {
          SpeechRecognition.startListening({ continuous: true, language: "en-US" });
        }
      },
      onSpeechEnd: (audio) => {
        if (cancelled) return;
        setUserSpeaking(false);
        void onAudioSegmentRef.current?.(audio);
        if (silenceTimer.current) clearTimeout(silenceTimer.current);
        silenceTimer.current = setTimeout(commitPhrase, 350);
      },
      positiveSpeechThreshold: 0.3,
      negativeSpeechThreshold: 0.25,
      redemptionFrames: 8,
      preSpeechPadFrames: 10,
      minSpeechFrames: 3,
      onnxWASMBasePath: "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/",
      baseAssetPath: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/",
      startOnLoad: false,
    })
      .then((instance) => {
        if (cancelled) {
          instance.destroy?.();
          return;
        }
        vadRef.current = instance;
        setVadLoading(false);
        setVadReady(true);
        console.info("[VAD] Silero VAD loaded via CDN — VAD-gated capture active.");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setVadLoading(false);
        setVadErrored(true);
        console.error("[VAD] Failed to initialise MicVAD:", err);
        if (onErrorRef.current) {
          const msg = err instanceof Error ? err.message : String(err);
          onErrorRef.current(
            msg ? `VAD error: ${msg} — falling back to basic speech recognition`
                : "VAD failed to load — falling back to basic speech recognition",
          );
        }
      });

    return () => {
      cancelled = true;
      vadRef.current?.destroy?.();
      vadRef.current = null;
    };
    // commitPhrase is stable; browserSupportsSpeechRecognition is constant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* React to `enabled` flips. */
  useEffect(() => {
    if (!browserSupportsSpeechRecognition) {
      if (enabled && onErrorRef.current) {
        onErrorRef.current(
          "Browser does not support speech recognition. Use Chrome or Edge.",
        );
      }
      return;
    }

    if (enabled) {
      if (vadReady && vadRef.current) {
        vadRef.current.start();
      } else if (!vadLoading) {
        SpeechRecognition.startListening({ continuous: true, language: "en-US" });
      }
    } else {
      vadRef.current?.pause();
      SpeechRecognition.stopListening();
      resetTranscript();
      lastFinal.current = "";
      if (silenceTimer.current) clearTimeout(silenceTimer.current);
      setUserSpeaking(false);
    }

    return () => {
      SpeechRecognition.stopListening();
      if (silenceTimer.current) clearTimeout(silenceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, vadReady, browserSupportsSpeechRecognition]);

  /* Accumulate final transcript + fallback silence timer. */
  useEffect(() => {
    if (!finalTranscript || muted) return;
    lastFinal.current = finalTranscript;
    if (!vadReady) {
      if (silenceTimer.current) clearTimeout(silenceTimer.current);
      silenceTimer.current = setTimeout(commitPhrase, silenceMs);
    }
  }, [finalTranscript, muted, commitPhrase, silenceMs, vadReady]);

  const reset = useCallback(() => {
    lastFinal.current = "";
    resetTranscript();
    if (silenceTimer.current) clearTimeout(silenceTimer.current);
  }, [resetTranscript]);

  return {
    interimText: interimTranscript,
    fullText: transcript,
    listening,
    userSpeaking,
    supported: browserSupportsSpeechRecognition,
    vadReady,
    vadLoading,
    vadErrored,
    flush: commitPhrase,
    reset,
  };
}
