/**
 * useVoiceCapture — VAD-enhanced speech recognition hook.
 *
 * Combines @ricky0123/vad-react (Silero VAD) with react-speech-recognition
 * (Web Speech API) to solve the "missed first words" problem.
 *
 * Strategy:
 *   - VAD runs continuously while `enabled` is true, detecting speech onset
 *     near-instantly via the Silero neural-network model.
 *   - When VAD fires `onSpeechStart`, we immediately kick off Web Speech API
 *     recognition so it's already listening when words arrive.
 *   - When VAD fires `onSpeechEnd`, we commit whatever text the Web Speech API
 *     has captured as a complete utterance.
 *   - The VAD's `preSpeechPadMs` (default 800ms) buffers audio *before* the
 *     detected speech start, compensating for the Web Speech API startup lag.
 *
 * Falls back to plain react-speech-recognition if VAD fails to load.
 */
import { useEffect, useRef, useCallback, useState } from "react";
import SpeechRecognition, {
  useSpeechRecognition,
} from "react-speech-recognition";
import { useMicVAD } from "@ricky0123/vad-react";

/**
 * @param {Object} opts
 * @param {boolean}  opts.enabled     — whether capture is active
 * @param {boolean}  opts.muted       — soft-mute (ignore transcripts but keep mic open)
 * @param {function} opts.onUtterance — called with (finalText: string) when a phrase ends
 * @param {function} opts.onError     — called with (message: string) on failure
 * @param {number}   [opts.silenceMs=2500] — fallback silence timeout (only used when VAD is unavailable)
 */
export default function useVoiceCapture({
  enabled = false,
  muted = false,
  onUtterance,
  onError,
  silenceMs = 2500,
}) {
  /* ── Web Speech API ── */
  const {
    transcript,
    interimTranscript,
    finalTranscript,
    resetTranscript,
    listening,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  /* ── Refs to avoid stale closures ── */
  const onUtteranceRef = useRef(onUtterance);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onUtteranceRef.current = onUtterance;
  }, [onUtterance]);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const lastFinal = useRef("");
  const silenceTimer = useRef(null);
  const [vadReady, setVadReady] = useState(false);

  /* ── Commit whatever text we have ── */
  const commitPhrase = useCallback(() => {
    if (muted) return;
    const text = lastFinal.current.trim();
    if (text && onUtteranceRef.current) {
      onUtteranceRef.current(text);
    }
    lastFinal.current = "";
    resetTranscript();
  }, [muted, resetTranscript]);

  /* ── VAD callbacks ── */
  const handleSpeechStart = useCallback(() => {
    if (!enabled || muted) return;
    // Kick off Web Speech API immediately so it's listening when words arrive
    if (browserSupportsSpeechRecognition) {
      SpeechRecognition.startListening({ continuous: true, language: "en-US" });
    }
  }, [enabled, muted, browserSupportsSpeechRecognition]);

  const handleSpeechEnd = useCallback(
    (_audio) => {
      // _audio is Float32Array @ 16kHz — we could send this to a server-side
      // ASR engine in the future, but for now we rely on Web Speech API text.
      if (!enabled || muted) return;

      // Give Web Speech API a tiny window to finalize its last transcript
      clearTimeout(silenceTimer.current);
      silenceTimer.current = setTimeout(() => {
        commitPhrase();
      }, 350);
    },
    [enabled, muted, commitPhrase]
  );

  /* ── VAD hook (always called — React hooks rules) ── */
  const vad = useMicVAD({
    startOnLoad: false,
    onSpeechStart: handleSpeechStart,
    onSpeechEnd: handleSpeechEnd,
    positiveSpeechThreshold: 0.3,
    negativeSpeechThreshold: 0.25,
    redemptionMs: 1400,
    preSpeechPadMs: 800,
    minSpeechMs: 400,
    // Assets are served from public/ — copied from node_modules at install time
    modelURL: "/silero_vad_legacy.onnx",
    workletURL: "/vad.worklet.bundle.min.js",
    ortConfig: (ort) => {
      ort.env.wasm.wasmPaths = "/";
    },
  });

  /* ── Track VAD readiness ── */
  useEffect(() => {
    if (vad && !vad.loading && !vad.errored) {
      setVadReady(true);
    }
    if (vad && vad.errored) {
      setVadReady(false);
      if (onErrorRef.current) {
        const msg =
          typeof vad.errored === "object" && vad.errored.message
            ? vad.errored.message
            : "VAD failed to load — falling back to basic speech recognition";
        onErrorRef.current(msg);
      }
    }
  }, [vad.loading, vad.errored]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Start/stop VAD + Speech API based on `enabled` ── */
  useEffect(() => {
    if (!browserSupportsSpeechRecognition) {
      if (enabled && onErrorRef.current) {
        onErrorRef.current(
          "Browser does not support speech recognition. Use Chrome or Edge."
        );
      }
      return;
    }

    if (enabled) {
      // Start VAD if ready
      if (vadReady && !vad.listening) {
        vad.start();
      }
      // If VAD is not ready yet, fall back to plain continuous listening
      if (!vadReady) {
        SpeechRecognition.startListening({
          continuous: true,
          language: "en-US",
        });
      }
    } else {
      // Stop everything
      if (vad.listening) {
        vad.pause();
      }
      SpeechRecognition.stopListening();
      resetTranscript();
      lastFinal.current = "";
      clearTimeout(silenceTimer.current);
    }

    return () => {
      SpeechRecognition.stopListening();
      clearTimeout(silenceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, browserSupportsSpeechRecognition, vadReady]);

  /* ── Watch finalTranscript — accumulate + set fallback silence timer ── */
  useEffect(() => {
    if (!finalTranscript || muted) return;

    lastFinal.current = finalTranscript;

    // If VAD is active, it handles silence detection via onSpeechEnd.
    // Otherwise use the fallback timer.
    if (!vadReady) {
      clearTimeout(silenceTimer.current);
      silenceTimer.current = setTimeout(commitPhrase, silenceMs);
    }
  }, [finalTranscript, muted, commitPhrase, silenceMs, vadReady]);

  return {
    /** Current partial (interim) transcript being spoken */
    interimText: interimTranscript,
    /** Full accumulated transcript (may include partial) */
    fullText: transcript,
    /** Whether the mic is actively listening */
    listening,
    /** Whether the user is currently speaking (from VAD) */
    userSpeaking: vad.userSpeaking,
    /** Whether the browser supports speech recognition */
    supported: browserSupportsSpeechRecognition,
    /** Whether VAD is loaded and ready */
    vadReady,
    /** Whether VAD is still loading */
    vadLoading: vad.loading,
    /** Whether VAD encountered an error */
    vadErrored: !!vad.errored,
    /** Manually commit whatever has been said so far */
    flush: commitPhrase,
    /** Reset everything */
    reset: useCallback(() => {
      lastFinal.current = "";
      resetTranscript();
      clearTimeout(silenceTimer.current);
    }, [resetTranscript]),
  };
}
