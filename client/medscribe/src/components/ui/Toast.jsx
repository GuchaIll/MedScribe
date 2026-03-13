import { useEffect } from "react";

/* ─── Notification Toast ─────────────────────────────────────────────────── */
function Toast({ message, type = "info", onClose }) {
  const bg =
    type === "error"
      ? "rgba(239,68,68,0.15)"
      : type === "success"
      ? "rgba(34,197,94,0.15)"
      : "rgba(59,130,246,0.15)";
  const border =
    type === "error"
      ? "rgba(239,68,68,0.3)"
      : type === "success"
      ? "rgba(34,197,94,0.3)"
      : "rgba(59,130,246,0.3)";
  const color =
    type === "error" ? "#ef4444" : type === "success" ? "#22c55e" : "#3b82f6";

  useEffect(() => {
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 20,
        right: 20,
        zIndex: 999,
        padding: "10px 20px",
        borderRadius: 10,
        background: bg,
        border: `1px solid ${border}`,
        color,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "'DM Mono', monospace",
        animation: "fadeUp 0.3s ease forwards",
        boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
      }}
    >
      {message}
    </div>
  );
}

export default Toast;
