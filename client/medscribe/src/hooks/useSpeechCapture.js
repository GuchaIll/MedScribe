/**
 * useSpeechCapture — real-time speech recognition hook.
 *
 * Uses react-speech-recognition (Web Speech API) for continuous listening.
 * Accumulates phrases and fires `onUtterance(text)` when the speaker pauses.
 *
 * Falls back gracefully if the browser doesn't support the Web Speech API
 * (e.g. Firefox — shows a toast via onError).
 */
import { useEffect, useRef, useCallback } from "react";
import SpeechRecognition, {
  useSpeechRecognition,
} from "react-speech-recognition";

/**
 * @param {Object} opts
 * @param {boolean}  opts.enabled    — whether mic capture is active
 * @param {boolean}  opts.muted      — soft-mute (ignore transcripts but keep mic open)
 * @param {function} opts.onUtterance — called with (finalText: string) when a phrase ends
 * @param {function} opts.onError     — called with (message: string) on failure
 * @param {number}   [opts.silenceMs=1500] — ms of silence before committing a phrase
 */
export default function useSpeechCapture({
  enabled = false,
  muted = false,
  onUtterance,
  onError,
  silenceMs = 2500,
}) {
  const {
    transcript,
    interimTranscript,
    finalTranscript,
    resetTranscript,
    listening,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  const silenceTimer = useRef(null);
  const lastFinal = useRef("");

  // Store callbacks in refs to prevent stale closures & dependency cascades.
  // Without this, commitPhrase → useEffect chain re-runs every time the
  // parent recreates onUtterance (e.g. when timer.seconds ticks), which
  // clears the silence timeout before it can fire.
  const onUtteranceRef = useRef(onUtterance);
  const onErrorRef = useRef(onError);
  useEffect(() => { onUtteranceRef.current = onUtterance; }, [onUtterance]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  // Start / stop listening based on `enabled`
  useEffect(() => {
    if (!browserSupportsSpeechRecognition) {
      if (enabled && onErrorRef.current) {
        onErrorRef.current("Browser does not support speech recognition. Use Chrome or Edge.");
      }
      return;
    }

    if (enabled) {
      SpeechRecognition.startListening({ continuous: true, language: "en-US" });
    } else {
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
  }, [enabled, browserSupportsSpeechRecognition]);

  // Commit phrase after silence — reads callbacks from refs so deps stay stable
  const commitPhrase = useCallback(() => {
    if (muted) return;
    const text = lastFinal.current.trim();
    if (text && onUtteranceRef.current) {
      onUtteranceRef.current(text);
    }
    lastFinal.current = "";
    resetTranscript();
  }, [muted, resetTranscript]);

  // Watch finalTranscript changes — accumulate and set silence timer
  useEffect(() => {
    if (!finalTranscript || muted) return;

    lastFinal.current = finalTranscript;

    // Reset silence timer
    clearTimeout(silenceTimer.current);
    silenceTimer.current = setTimeout(commitPhrase, silenceMs);
  }, [finalTranscript, muted, commitPhrase, silenceMs]);

  return {
    /** Current partial (interim) transcript being spoken */
    interimText: interimTranscript,
    /** Full accumulated transcript (may include partial) */
    fullText: transcript,
    /** Whether the mic is actively listening */
    listening,
    /** Whether the browser supports speech recognition */
    supported: browserSupportsSpeechRecognition,
    /** Manually commit whatever has been said so far */
    flush: commitPhrase,
    /** Reset everything */
    reset: () => {
      resetTranscript();
      lastFinal.current = "";
      clearTimeout(silenceTimer.current);
    },
  };
}
