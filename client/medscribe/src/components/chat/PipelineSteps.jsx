/* ─── Inline Pipeline Steps (bubble) ─────────────────────────────────────── */
function PipelineSteps({ steps }) {
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 7 }}
    >
      {steps.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 9, color: "#4ade80", lineHeight: 1 }}>
            ✓
          </span>
          <span
            style={{
              fontSize: 10,
              color: "rgba(255,255,255,0.32)",
              fontFamily: "'DM Mono', monospace",
              fontStyle: "italic",
            }}
          >
            {s.label}
          </span>
        </div>
      ))}
    </div>
  );
}

export default PipelineSteps;
