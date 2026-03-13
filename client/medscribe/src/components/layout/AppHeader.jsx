import GlassPanel from "../ui/GlassPanel";

export default function AppHeader({
  sessionActive,
  sessionId,
  tab,
  onStartSession,
  onEndSession,
  onTabChange,
}) {
  return (
    <GlassPanel
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 28px",
        height: 58,
        flexShrink: 0,
        zIndex: 30,
        borderLeft: "none",
        borderRight: "none",
        borderTop: "none",
        borderRadius: 0,
        boxShadow:
          "0 6px 36px rgba(0,0,0,0.45), 0 1px 0 rgba(255,255,255,0.06)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {!sessionActive ? (
          <button
            onClick={onStartSession}
            className="ib"
            style={{
              padding: "5px 14px",
              borderRadius: 99,
              border: "1px solid rgba(34,197,94,0.3)",
              background: "rgba(34,197,94,0.1)",
              cursor: "pointer",
              color: "#22c55e",
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "inherit",
              transition: "all 0.18s",
            }}
          >
            ▶ Start Session
          </button>
        ) : (
          <button
            onClick={onEndSession}
            className="ib"
            style={{
              padding: "5px 14px",
              borderRadius: 99,
              border: "1px solid rgba(239,68,68,0.3)",
              background: "rgba(239,68,68,0.1)",
              cursor: "pointer",
              color: "#ef4444",
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "inherit",
              transition: "all 0.18s",
            }}
          >
            ■ End Session
          </button>
        )}
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "rgba(255,255,255,0.82)",
            letterSpacing: "-0.02em",
          }}
        >
          {sessionActive ? "Active Session" : "MedScribe"}
        </span>
      </div>

      <div
        style={{
          display: "flex",
          gap: 2,
          background: "rgba(255,255,255,0.05)",
          borderRadius: 99,
          padding: "3px",
          border: "1px solid rgba(255,255,255,0.07)",
        }}
      >
        {["Transcription", "Patient Info"].map((t) => (
          <button
            key={t}
            onClick={() => onTabChange(t)}
            style={{
              padding: "5px 16px",
              borderRadius: 99,
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.01em",
              background: tab === t ? "rgba(255,255,255,0.12)" : "transparent",
              color:
                tab === t
                  ? "rgba(255,255,255,0.9)"
                  : "rgba(255,255,255,0.35)",
              boxShadow: tab === t ? "0 1px 6px rgba(0,0,0,0.3)" : "none",
              transition: "all 0.18s",
              fontFamily: "inherit",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {sessionActive && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 11px",
              borderRadius: 99,
              background: "rgba(239,68,68,0.1)",
              border: "1px solid rgba(239,68,68,0.22)",
            }}
          >
            <div
              className="blink"
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "#ef4444",
              }}
            />
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.12em",
                color: "#ef4444",
                fontFamily: "'DM Mono', monospace",
              }}
            >
              LIVE
            </span>
          </div>
        )}
        {sessionId && (
          <span
            style={{
              fontSize: 9,
              color: "rgba(255,255,255,0.2)",
              fontFamily: "'DM Mono', monospace",
            }}
          >
            {sessionId.slice(0, 8)}
          </span>
        )}
      </div>
    </GlassPanel>
  );
}
