import GlassPanel from "../ui/GlassPanel";
import FluidWave from "../ui/FluidWave";
import { PIPELINE_STEPS } from "../../constants";

export default function Footer({
  waveActive,
  transcribing,
  pipelineRunning,
  pipelineStep,
  speech,
  sessionActive,
  recording,
  muted,
  demoText,
  setDemoText,
  uploadOpen,
  onToggleRecording,
  onToggleMuted,
  onCompleteTranscription,
  onToggleUpload,
  onSendUtterance,
}) {
  return (
    <GlassPanel
      style={{
        padding: "0 44px 20px",
        flexShrink: 0,
        zIndex: 20,
        borderLeft: "none",
        borderRight: "none",
        borderBottom: "none",
        borderRadius: 0,
        boxShadow:
          "0 -8px 40px rgba(0,0,0,0.45), 0 -1px 0 rgba(255,255,255,0.06)",
        background:
          "linear-gradient(to top, rgba(61,61,61,0.85) 0%, rgba(61,61,61,0.72) 50%, rgba(255,255,255,1.0) 100%)",
        WebkitMaskImage:
          "linear-gradient(to top, black 0%, black 50%, transparent 100%)",
        maskImage:
          "linear-gradient(to top, black 0%, black 50%, transparent 100%)",
      }}
    >
      {/* Waveform */}
      <div
        style={{
          height: 76,
          maxWidth: 680,
          width: "100%",
          margin: "0 auto",
        }}
      >
        <FluidWave active={waveActive} />
      </div>

      {/* Agent status */}
      <div
        style={{
          maxWidth: 680,
          margin: "0 auto 10px",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {transcribing ? (
          <>
            <div
              className="blink"
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "rgba(255,255,255,0.3)",
              }}
            />
            <span
              style={{
                fontSize: 10,
                color: "rgba(255,255,255,0.28)",
                fontFamily: "'DM Mono', monospace",
                fontStyle: "italic",
              }}
            >
              {PIPELINE_STEPS[pipelineStep]}
            </span>
            {speech.vadReady && (
              <span
                style={{
                  fontSize: 9,
                  color: "rgba(34,197,94,0.5)",
                  fontFamily: "'DM Mono', monospace",
                  marginLeft: "auto",
                }}
              >
                VAD ✓
              </span>
            )}
            {speech.vadLoading && (
              <span
                style={{
                  fontSize: 9,
                  color: "rgba(234,179,8,0.5)",
                  fontFamily: "'DM Mono', monospace",
                  marginLeft: "auto",
                }}
              >
                VAD loading…
              </span>
            )}
          </>
        ) : pipelineRunning ? (
          <>
            <div
              className="blink"
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "rgba(120,195,255,0.5)",
              }}
            />
            <span
              style={{
                fontSize: 10,
                color: "rgba(120,195,255,0.5)",
                fontFamily: "'DM Mono', monospace",
                fontStyle: "italic",
              }}
            >
              Running full pipeline…
            </span>
          </>
        ) : (
          <span
            style={{
              fontSize: 10,
              color: "rgba(255,255,255,0.18)",
              fontFamily: "'DM Mono', monospace",
              fontStyle: "italic",
            }}
          >
            {sessionActive
              ? "All agents idle · session active"
              : "No active session"}
          </span>
        )}
      </div>

      {/* Text input for manual utterances */}
      {sessionActive && (
        <div style={{ maxWidth: 680, margin: "0 auto 10px" }}>
          {speech.interimText && (
            <div
              style={{
                marginBottom: 8,
                padding: "6px 14px",
                borderRadius: 10,
                background: "rgba(120,195,255,0.08)",
                border: "1px solid rgba(120,195,255,0.15)",
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  color: "rgba(120,195,255,0.6)",
                  fontFamily: "'DM Mono', monospace",
                  fontStyle: "italic",
                }}
              >
                🎙 {speech.interimText}
              </span>
            </div>
          )}
          {recording && !muted && !speech.supported && (
            <div
              style={{
                marginBottom: 8,
                padding: "4px 12px",
                borderRadius: 8,
                background: "rgba(234,179,8,0.1)",
                border: "1px solid rgba(234,179,8,0.2)",
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  color: "#a16207",
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                ⚠ Speech recognition not supported — use Chrome/Edge or type
                manually
              </span>
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={demoText}
              onChange={(e) => setDemoText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && demoText.trim()) {
                  onSendUtterance(demoText);
                  setDemoText("");
                }
              }}
              placeholder="Type or speak an utterance…"
              style={{
                flex: 1,
                padding: "8px 14px",
                borderRadius: 99,
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "rgba(255,255,255,0.85)",
                fontSize: 12,
                fontFamily: "'DM Sans', sans-serif",
              }}
            />
            <button
              onClick={() => {
                if (demoText.trim()) {
                  onSendUtterance(demoText);
                  setDemoText("");
                }
              }}
              style={{
                padding: "8px 16px",
                borderRadius: 99,
                background: "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.12)",
                color: "rgba(255,255,255,0.6)",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}

      {/* Controls */}
      <div
        style={{
          maxWidth: 680,
          margin: "0 auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        {/* Pause/Resume */}
        <button
          onClick={onToggleRecording}
          disabled={!sessionActive}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "none",
            border: "none",
            cursor: sessionActive ? "pointer" : "not-allowed",
            color: recording
              ? "rgba(255,255,255,0.28)"
              : "rgba(255,255,255,0.7)",
            fontSize: 12,
            fontWeight: 600,
            fontFamily: "inherit",
            transition: "color 0.18s",
            opacity: sessionActive ? 1 : 0.3,
          }}
        >
          <span style={{ fontSize: 15 }}>{recording ? "⏸" : "▶"}</span>
          {recording ? "Pause" : "Resume"}
        </button>

        {/* Center controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <button
            onClick={onToggleMuted}
            disabled={!sessionActive}
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              background: muted
                ? "rgba(239,68,68,0.12)"
                : "rgba(255,255,255,0.07)",
              border: muted
                ? "1px solid rgba(239,68,68,0.3)"
                : "1px solid rgba(255,255,255,0.1)",
              cursor: sessionActive ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: muted ? "#ef4444" : "rgba(255,255,255,0.45)",
              fontSize: 15,
              transition: "all 0.18s",
              boxShadow: "0 2px 10px rgba(0,0,0,0.3)",
              opacity: sessionActive ? 1 : 0.3,
            }}
          >
            {muted ? "🔇" : "🎙"}
          </button>

          <button
            onClick={onCompleteTranscription}
            disabled={!sessionActive || pipelineRunning}
            style={{
              padding: "9px 24px",
              borderRadius: 99,
              background: pipelineRunning
                ? "rgba(120,195,255,0.15)"
                : "rgba(255,255,255,0.08)",
              border: pipelineRunning
                ? "1px solid rgba(120,195,255,0.3)"
                : "1px solid rgba(255,255,255,0.12)",
              color: pipelineRunning
                ? "rgba(120,195,255,0.7)"
                : "rgba(255,255,255,0.75)",
              fontWeight: 600,
              fontSize: 12,
              cursor:
                sessionActive && !pipelineRunning ? "pointer" : "not-allowed",
              fontFamily: "inherit",
              letterSpacing: "0.02em",
              boxShadow: "0 2px 12px rgba(0,0,0,0.3)",
              transition: "all 0.18s",
              opacity: sessionActive ? 1 : 0.3,
            }}
            onMouseEnter={(e) => {
              if (sessionActive && !pipelineRunning) {
                e.currentTarget.style.background = "rgba(255,255,255,0.14)";
                e.currentTarget.style.color = "rgba(255,255,255,0.95)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = pipelineRunning
                ? "rgba(120,195,255,0.15)"
                : "rgba(255,255,255,0.08)";
              e.currentTarget.style.color = pipelineRunning
                ? "rgba(120,195,255,0.7)"
                : "rgba(255,255,255,0.75)";
            }}
          >
            {pipelineRunning ? "Processing…" : "Complete Transcription"}
          </button>
        </div>

        {/* Upload */}
        <button
          onClick={onToggleUpload}
          disabled={!sessionActive}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            background: uploadOpen ? "rgba(255,255,255,0.08)" : "none",
            border: uploadOpen
              ? "1px solid rgba(255,255,255,0.1)"
              : "1px solid transparent",
            borderRadius: 99,
            padding: "6px 12px",
            cursor: sessionActive ? "pointer" : "not-allowed",
            color: uploadOpen
              ? "rgba(255,255,255,0.65)"
              : "rgba(255,255,255,0.28)",
            fontSize: 12,
            fontWeight: 600,
            fontFamily: "inherit",
            transition: "all 0.18s",
            opacity: sessionActive ? 1 : 0.3,
          }}
        >
          Upload Doc <span style={{ fontSize: 13 }}>⬆</span>
        </button>
      </div>
    </GlassPanel>
  );
}
