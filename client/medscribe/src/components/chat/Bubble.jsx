import { useState } from "react";
import Avatar from "../ui/Avatar";
import AgentCard from "./AgentCard";

/* ─── Bubble ─────────────────────────────────────────────────────────────── */
function Bubble({ msg, visible, onApprove, onSwitchTab }) {
  const isDoc = msg.speaker.role === "Physician";
  const isAgent = msg.speaker.role === "Agent";
  const [hov, setHov] = useState(false);

  if (isAgent)
    return (
      <AgentCard
        msg={msg}
        visible={visible}
        onApprove={onApprove}
        onSwitchTab={onSwitchTab}
      />
    );

  return (
    <div
      style={{
        display: "flex",
        gap: 11,
        flexDirection: isDoc ? "row" : "row-reverse",
        alignItems: "flex-start",
        maxWidth: 580,
        marginLeft: isDoc ? 0 : "auto",
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(16px)",
        transition: "opacity 0.42s ease, transform 0.42s ease",
      }}
    >
      <Avatar src={msg.speaker.avatar} online={isDoc} />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 5,
          alignItems: isDoc ? "flex-start" : "flex-end",
          minWidth: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexDirection: isDoc ? "row" : "row-reverse",
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "#1a1a1a",
              letterSpacing: "-0.01em",
            }}
          >
            {msg.speaker.name}
          </span>
          <span
            style={{
              fontSize: 10,
              color: "#b0b0b8",
              fontFamily: "'DM Mono', monospace",
            }}
          >
            {msg.time}
          </span>
        </div>

        <div
          onMouseEnter={() => setHov(true)}
          onMouseLeave={() => setHov(false)}
          style={{
            padding: "13px 16px 10px",
            borderRadius: isDoc
              ? "4px 16px 16px 16px"
              : "16px 4px 16px 16px",
            background: isDoc
              ? hov
                ? "rgba(0,0,0,0.05)"
                : "rgba(0,0,0,0.03)"
              : hov
              ? "rgba(0,0,0,0.06)"
              : "rgba(0,0,0,0.04)",
            border: "1px solid rgba(0,0,0,0.08)",
            boxShadow: hov
              ? "0 6px 24px rgba(0,0,0,0.10), inset 0 1px 0 rgba(255,255,255,0.9)"
              : "0 2px 8px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.7)",
            transform: hov ? "translateY(-1px)" : "translateY(0)",
            transition: "all 0.2s ease",
            cursor: "default",
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 14,
              lineHeight: 1.72,
              color: "#1a1a1a",
              fontFamily: "'Lora', Georgia, serif",
              textAlign: isDoc ? "left" : "right",
            }}
          >
            {msg.text}
          </p>
        </div>
      </div>
    </div>
  );
}

export default Bubble;
