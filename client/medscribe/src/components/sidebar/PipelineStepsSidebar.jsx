/* ─── Pipeline Steps (sidebar) ───────────────────────────────────────────── */
function PipelineStepsSidebar({ steps, currentStep, active }) {
  return (
    <div style={{ padding: "0 8px" }}>
      <span
        style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.2)",
          fontFamily: "'DM Mono', monospace",
          display: "block",
          marginBottom: 8,
        }}
      >
        Pipeline
      </span>
      {steps.map((step, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            marginBottom: 6,
            opacity: active
              ? i === currentStep
                ? 1
                : i < currentStep
                ? 0.45
                : 0.15
              : 0.32,
            transition: "opacity 0.4s ease",
          }}
        >
          <div
            style={{
              width: 13,
              height: 13,
              borderRadius: "50%",
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background:
                active && i === currentStep
                  ? "rgba(120,195,255,0.25)"
                  : i < currentStep || !active
                  ? "rgba(255,255,255,0.12)"
                  : "transparent",
              border:
                active && i === currentStep
                  ? "1px solid rgba(120,195,255,0.5)"
                  : "1px solid rgba(255,255,255,0.15)",
              fontSize: 7,
              color: "rgba(255,255,255,0.7)",
              transition: "all 0.3s",
            }}
          >
            {i < currentStep || !active ? "✓" : ""}
          </div>
          <span
            style={{
              fontSize: 10,
              color:
                active && i === currentStep
                  ? "rgba(255,255,255,0.75)"
                  : "rgba(255,255,255,0.32)",
              fontFamily: "'DM Mono', monospace",
              fontStyle: "italic",
              transition: "color 0.3s",
            }}
          >
            {step.replace("…", "")}
          </span>
        </div>
      ))}
    </div>
  );
}

export default PipelineStepsSidebar;
