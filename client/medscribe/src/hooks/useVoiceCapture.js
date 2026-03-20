/**
 * useVoiceCapture â€” VAD-enhanced speech recognition hook.
 *
 * Uses @ricky0123/vad-web (Silero VAD) loaded from CDN via window.vad,
 * combined with react-speech-recognition (Web Speech API).
 *
 * Strategy:
 *   - On mount, we call window.vad.MicVAD.new() imperatively so the ONNX
 *     runtime is pulled from the same CDN as the model â€” no COOP/COEP headers
 *     required, no local /public asset copies needed.
 *   - When VAD fires onSpeechStart, Web Speech API starts immediately.
 *   - When VAD fires onSpeechEnd, we commit whatever the Web Speech API captured.
 *   - Falls back to plain continuous Web Speech API if VAD fails to load.
 */
import { useEffect, useRef, useCallback, useState } from "react";
import SpeechRecognition, {
  useSpeechRecognition,
} from "react-speech-recognition";

/**
 * @param {Object} opts
 * @param {boolean}  opts.enabled     â€” whether capture is active
 * @param {boolean}  opts.muted       â€” soft-mute (ignore transcripts but keep mic open)
 * @param {function} opts.onUtterance â€” called with (finalText: string) when a phrase ends
 * @param {function} opts.onError     â€” called with (message: string) on failure
 * @param {number}   [opts.silenceMs=2500] â€” fallback silence timeout when VAD is unavailable
 */
export default function useVoiceCapture({
  enabled = false,
  muted = false,
  onUtterance,
  onError,
  silenceMs = 2500,
}) {
  /* â”€â”€ Web Speech API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const {
    transcript,
    interimTranscript,
    finalTranscript,
    resetTranscript,
    listening,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  /* â”€â”€ Stable refs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const onUtteranceRef = useRef(onUtterance);
  const onErrorRef     = useRef(onError);
  useEffect(() => { onUtteranceRef.current = onUtterance; }, [onUtterance]);
  useEffect(() => { onErrorRef.current     = onError;     }, [onError]);

  const lastFinal    = useRef("");
  const silenceTimer = useRef(null);

  /* â”€â”€ VAD state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const vadRef          = useRef(null);   // MicVAD instance
  const [vadReady,   setVadReady]   = useState(false);
  const [vadLoading, setVadLoading] = useState(false);
  const [vadErrored, setVadErrored] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);

  /* â”€â”€ Commit current phrase â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const commitPhrase = useCallback(() => {
    if (muted) return;
    const text = lastFinal.current.trim();
    if (text && onUtteranceRef.current) onUtteranceRef.current(text);
    lastFinal.current = "";
    resetTranscript();
  }, [muted, resetTranscript]);

  /* â”€â”€ Initialise VAD from CDN global (runs once) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  useEffect(() => {
    // window.vad is injected by the CDN bundle.min.js script tag in index.html.
    // If it's not there yet (e.g. script blocked), bail out gracefully.
    if (typeof window.vad === "undefined" || !window.vad?.MicVAD) {
      console.warn(
        "[VAD] window.vad not found â€” CDN scripts may not have loaded.\n" +
        "  Ensure index.html includes ort.wasm.min.js and bundle.min.js before </body>.\n" +
        "  Falling back to plain Web Speech API."
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
      onSpeechEnd: (_audio) => {
        if (cancelled) return;
        setUserSpeaking(false);
        // Short delay so Web Speech API can finalize its last interim result.
        clearTimeout(silenceTimer.current);
        silenceTimer.current = setTimeout(commitPhrase, 350);
      },
      positiveSpeechThreshold: 0.3,
      negativeSpeechThreshold: 0.25,
      redemptionFrames: 8,
      preSpeechPadFrames: 10,
      minSpeechFrames: 3,
      // Tell the ONNX runtime and model loader to pull assets from the same
      // CDN rather than looking for files in /public.
      onnxWASMBasePath:
        "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/",
      baseAssetPath:
        "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/",
      // Start paused â€” we call .start() / .pause() ourselves.
      startOnLoad: false,
    })
      .then((instance) => {
        if (cancelled) {
          try { instance.destroy?.(); } catch { /* ignore */ }
          return;
        }
        vadRef.current = instance;
        setVadLoading(false);
        setVadReady(true);
        console.info("[VAD] Silero VAD loaded via CDN â€” VAD-gated capture active.");
      })
      .catch((err) => {
        if (cancelled) return;
        setVadLoading(false);
        setVadErrored(true);
        console.error("[VAD] Failed to initialise MicVAD:", err);
        console.error(
          "[VAD] Diagnostic checklist:\n" +
          "  â€¢ Open Network tab and verify the CDN scripts loaded (200 OK).\n" +
          "  â€¢ Check for Content-Security-Policy headers blocking cdn.jsdelivr.net.\n" +
          "  â€¢ Ensure the page is served over HTTPS or localhost.\n" +
          "  Falling back to plain Web Speech API (no VAD gating)."
        );
        if (onErrorRef.current) {
          onErrorRef.current(
            err?.message
              ? `VAD error: ${err.message} â€” falling back to basic speech recognition`
              : "VAD failed to load â€” falling back to basic speech recognition"
          );
        }
      });

    return () => {
      cancelled = true;
      try { vadRef.current?.destroy?.(); } catch { /* ignore */ }
      vadRef.current = null;
    };
    // commitPhrase is stable; browserSupportsSpeechRecognition is constant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* â”€â”€ Start / pause VAD + Speech API when `enabled` changes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
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
      if (vadReady && vadRef.current) {
        vadRef.current.start();
      } else if (!vadLoading) {
        // VAD unavailable â€” fall straight through to continuous Web Speech API.
        SpeechRecognition.startListening({ continuous: true, language: "en-US" });
      }
    } else {
      try { vadRef.current?.pause(); } catch { /* ignore */ }
      SpeechRecognition.stopListening();
      resetTranscript();
      lastFinal.current = "";
      clearTimeout(silenceTimer.current);
      setUserSpeaking(false);
    }

    return () => {
      SpeechRecognition.stopListening();
      clearTimeout(silenceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, vadReady, browserSupportsSpeechRecognition]);

  /* â”€â”€ Accumulate final transcript + fallback silence timer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  useEffect(() => {
    if (!finalTranscript || muted) return;
    lastFinal.current = finalTranscript;
    if (!vadReady) {
      clearTimeout(silenceTimer.current);
      silenceTimer.current = setTimeout(commitPhrase, silenceMs);
    }
  }, [finalTranscript, muted, commitPhrase, silenceMs, vadReady]);

  return {
    /** Current partial (interim) transcript being spoken */
    interimText: interimTranscript,
    /** Full accumulated transcript */
    fullText: transcript,
    /** Whether the mic is actively listening (Web Speech API) */
    listening,
    /** Whether the user is currently speaking (from VAD) */
    userSpeaking,
    /** Whether the browser supports speech recognition */
    supported: browserSupportsSpeechRecognition,
    /** Whether VAD is loaded and ready */
    vadReady,
    /** Whether VAD is still initialising */
    vadLoading,
    /** Whether VAD encountered an error */
    vadErrored,
    /** Manually commit whatever has been said so far */
    flush: commitPhrase,
    /** Reset transcript buffer */
    reset: useCallback(() => {
      lastFinal.current = "";
      resetTranscript();
      clearTimeout(silenceTimer.current);
    }, [resetTranscript]),
  };
}

// â”€â”€ end of file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// (duplicate old useVoiceCapture body removed â€” hook now uses window.vad CDN)
