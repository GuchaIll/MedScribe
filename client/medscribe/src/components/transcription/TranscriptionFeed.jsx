import Bubble from "../chat/Bubble";
import LiveDot from "../ui/LiveDot";

export default function TranscriptionFeed({
  feedRef,
  sessionActive,
  msgs,
  vis,
  transcribing,
  pipelineRunning,
  currentNodeLabel,
  onApprove,
  onSwitchTab,
}) {
  return (
    <main
      ref={feedRef}
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "40px 56px 28px",
        display: "flex",
        flexDirection: "column",
        gap: 22,
        background: "#ffffff",
      }}
    >
      {!sessionActive && msgs.length === 0 && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
          }}
        >
          <span style={{ fontSize: 48, opacity: 0.2 }}>🎙</span>
          <p
            style={{
              fontSize: 16,
              color: "#999",
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            Click <strong>Start Session</strong> to begin transcription
          </p>
        </div>
      )}

      {msgs.map((m) => (
        <Bubble
          key={m.id}
          msg={m}
          visible={vis.has(m.id)}
          onApprove={onApprove}
          onSwitchTab={onSwitchTab}
        />
      ))}

      {transcribing && <LiveDot step={currentNodeLabel || "Listening…"} />}
      {pipelineRunning && <LiveDot step={currentNodeLabel || "Running pipeline…"} />}
    </main>
  );
}
