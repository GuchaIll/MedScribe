/* ─── Live indicator ─────────────────────────────────────────────────────── */
function LiveDot({ step }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 14px",
        borderRadius: 99,
        width: "fit-content",
        background: "rgba(0,0,0,0.04)",
        border: "1px solid rgba(0,0,0,0.08)",
      }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="blink"
          style={{
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: "#b0b0bc",
            animationDelay: `${i * 0.22}s`,
          }}
        />
      ))}
      <span
        style={{
          fontSize: 10,
          color: "#a0a0ac",
          fontFamily: "'DM Mono', monospace",
          fontStyle: "italic",
        }}
      >
        {step}
      </span>
    </div>
  );
}

export default LiveDot;
