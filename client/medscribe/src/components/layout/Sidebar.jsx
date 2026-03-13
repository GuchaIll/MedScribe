import GlassPanel from "../ui/GlassPanel";
import Avatar from "../ui/Avatar";
import PipelineStepsSidebar from "../sidebar/PipelineStepsSidebar";
import { PHYSICIAN, PATIENT, PIPELINE_STEPS } from "../../constants";

export default function Sidebar({ sessionActive, pipelineStep, transcribing, timer }) {
  return (
    <GlassPanel
      style={{
        width: 220,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        padding: "20px 12px",
        gap: 3,
        zIndex: 10,
        borderTop: "none",
        borderBottom: "none",
        borderLeft: "none",
        borderRadius: 0,
        boxShadow:
          "6px 0 40px rgba(0,0,0,0.4), 1px 0 0 rgba(255,255,255,0.05)",
        background:
          "linear-gradient(to right, rgba(61,61,61,0.85) 0%, rgba(61,61,61,0.72) 55%, rgba(255,255,255,1.0) 100%)",
        WebkitMaskImage:
          "linear-gradient(to right, black 0%, black 55%, transparent 100%)",
        maskImage:
          "linear-gradient(to right, black 0%, black 55%, transparent 100%)",
      }}
    >
      <span
        style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.2)",
          fontFamily: "'DM Mono', monospace",
          padding: "0 8px",
          marginBottom: 6,
        }}
      >
        Participants
      </span>

      {[
        { p: PHYSICIAN, online: sessionActive },
        { p: PATIENT, online: false },
      ].map(({ p, online }) => (
        <div
          key={p.name}
          className="pc"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 10px",
            borderRadius: 10,
            cursor: "pointer",
            transition: "background 0.16s",
          }}
        >
          <Avatar src={p.avatar} online={online} />
          <div>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: online
                  ? "rgba(120,195,255,0.6)"
                  : "rgba(255,255,255,0.22)",
                fontFamily: "'DM Mono', monospace",
                marginBottom: 2,
              }}
            >
              {p.role}
            </div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 500,
                color: "rgba(255,255,255,0.8)",
              }}
            >
              {p.name}
            </div>
          </div>
        </div>
      ))}

      <div
        style={{
          height: 1,
          background: "rgba(255,255,255,0.06)",
          margin: "8px 4px",
        }}
      />

      <PipelineStepsSidebar
        steps={PIPELINE_STEPS}
        currentStep={pipelineStep}
        active={transcribing}
      />

      <div style={{ marginTop: "auto" }}>
        <GlassPanel
          style={{
            padding: "14px 14px",
            borderRadius: 12,
            boxShadow:
              "0 4px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.07)",
          }}
        >
          <div
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.13em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.2)",
              fontFamily: "'DM Mono', monospace",
              marginBottom: 5,
            }}
          >
            Duration
          </div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: "rgba(255,255,255,0.85)",
              fontFamily: "'DM Mono', monospace",
              letterSpacing: "0.04em",
            }}
          >
            {timer.display}
          </div>
          <button
            onClick={timer.toggle}
            style={{
              marginTop: 7,
              fontSize: 11,
              fontWeight: 600,
              color: timer.running
                ? "rgba(255,255,255,0.22)"
                : "rgba(120,195,255,0.7)",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontFamily: "inherit",
              transition: "color 0.2s",
            }}
          >
            {timer.running ? "⏸ Pause" : "▶ Resume"}
          </button>
        </GlassPanel>
      </div>
    </GlassPanel>
  );
}
