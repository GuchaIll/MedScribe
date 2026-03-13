/* ─── Glass Panel ────────────────────────────────────────────────────────── */
const GlassPanel = ({ children, style = {}, className = "" }) => (
  <div
    className={className}
    style={{
      background: "rgba(61,61,61,0.72)",
      backdropFilter: "blur(32px) saturate(1.2)",
      WebkitBackdropFilter: "blur(32px) saturate(1.2)",
      border: "1px solid rgba(255,255,255,0.08)",
      boxShadow:
        "0 8px 40px rgba(0,0,0,0.35), 0 2px 10px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.07)",
      ...style,
    }}
  >
    {children}
  </div>
);

export default GlassPanel;
