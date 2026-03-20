/* ─── Pipeline Steps (sidebar) ───────────────────────────────────────────── */

import { PIPELINE_NODES } from "../../constants";

const PHASE_LABELS = {
  ingestion:  "Ingestion",
  extraction: "Extraction",
  validation: "Validation",
  output:     "Output",
};

const PHASES = ["ingestion", "extraction", "validation", "output"];

/**
 * Returns visual tokens for a given node status.
 */
function nodeStyle(status, pipelineRunning) {
  switch (status) {
    case "completed": return { dotBg: "rgba(34,197,94,0.18)",  dotBorder: "rgba(34,197,94,0.4)",       icon: "\u2713", textColor: "rgba(255,255,255,0.65)", opacity: 1,    running: false };
    case "running":   return { dotBg: "rgba(120,195,255,0.2)", dotBorder: "rgba(120,195,255,0.6)",     icon: "\u25cf", textColor: "rgba(255,255,255,0.92)", opacity: 1,    running: true  };
    case "failed":    return { dotBg: "rgba(239,68,68,0.18)",  dotBorder: "rgba(239,68,68,0.5)",       icon: "\u00d7", textColor: "rgba(239,68,68,0.85)",   opacity: 1,    running: false };
    case "skipped":   return { dotBg: "transparent",           dotBorder: "rgba(255,255,255,0.1)",     icon: "\u2013", textColor: "rgba(255,255,255,0.22)", opacity: 0.45, running: false };
    default:          return { dotBg: "transparent",           dotBorder: "rgba(255,255,255,0.12)",    icon: "",       textColor: "rgba(255,255,255,0.22)", opacity: pipelineRunning ? 0.28 : 0.18, running: false };
  }
}

/**
 * Formats a duration from milliseconds to a compact string.
 */
function fmtDuration(ms) {
  if (!ms) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function PipelineStepsSidebar({ pipelineNodes, pipelineRunning }) {
  // Merge API node data (with status/timing) over the static catalogue.
  const liveMap = {};
  (pipelineNodes || []).forEach((n) => { liveMap[n.name] = n; });

  // If no API data yet, render the static catalogue as "pending".
  const displayNodes = PIPELINE_NODES.map((def) => liveMap[def.name] ?? { ...def, status: "pending" });

  return (
    <div style={{ padding: "0 8px" }}>
      {/* Section heading */}
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

      {PHASES.map((phase) => {
        const nodes = displayNodes.filter((n) => n.phase === phase);
        if (nodes.length === 0) return null;

        const phaseCompleted = nodes.every(
          (n) => n.status === "completed" || n.status === "skipped"
        );
        const phaseActive = !phaseCompleted && nodes.some(
          (n) => n.status === "running" || n.status === "completed" || n.status === "failed"
        );

        return (
          <div key={phase} style={{ marginBottom: 10 }}>
            {/* Phase label */}
            <div
              style={{
                fontSize: 8,
                fontWeight: 700,
                letterSpacing: "0.13em",
                textTransform: "uppercase",
                color: phaseCompleted
                  ? "rgba(34,197,94,0.4)"
                  : phaseActive
                  ? "rgba(120,195,255,0.35)"
                  : "rgba(255,255,255,0.12)",
                fontFamily: "'DM Mono', monospace",
                marginBottom: 5,
                paddingLeft: 2,
                transition: "color 0.35s",
              }}
            >
              {phaseCompleted ? "\u2713 " : ""}{PHASE_LABELS[phase]}
            </div>

            {/* Nodes in this phase */}
            {nodes.map((node) => {
              const s = nodeStyle(node.status, pipelineRunning);
              return (
                <div
                  key={node.name}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 6,
                    marginBottom: 5,
                    opacity: s.opacity,
                    transition: "opacity 0.35s ease",
                  }}
                >
                  {/* Status dot / icon */}
                  <div
                    className={s.running ? "node-running" : undefined}
                    style={{
                      width: 13,
                      height: 13,
                      borderRadius: "50%",
                      flexShrink: 0,
                      marginTop: 1,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: s.dotBg,
                      border: `1px solid ${s.dotBorder}`,
                      fontSize: node.status === "running" ? 6 : 7,
                      color: node.status === "completed"
                        ? "rgba(34,197,94,0.8)"
                        : node.status === "failed"
                        ? "rgba(239,68,68,0.8)"
                        : node.status === "running"
                        ? "rgba(120,195,255,0.9)"
                        : "rgba(255,255,255,0.25)",
                      transition: "all 0.3s",
                    }}
                  >
                    {s.icon}
                  </div>

                  {/* Label + optional timings / detail */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: s.textColor,
                        fontFamily: "'DM Mono', monospace",
                        fontStyle: node.status === "running" ? "normal" : "italic",
                        fontWeight: node.status === "running" ? 600 : 400,
                        transition: "color 0.3s",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {node.label}
                      {node.status === "completed" && node.duration_ms != null && (
                        <span
                          style={{
                            fontSize: 8,
                            color: "rgba(255,255,255,0.2)",
                            marginLeft: 5,
                            fontStyle: "normal",
                            fontWeight: 400,
                          }}
                        >
                          {fmtDuration(node.duration_ms)}
                        </span>
                      )}
                    </div>

                    {node.detail && node.status !== "pending" && (
                      <div
                        style={{
                          fontSize: 8,
                          color: node.status === "failed"
                            ? "rgba(239,68,68,0.6)"
                            : "rgba(255,255,255,0.28)",
                          fontFamily: "'DM Mono', monospace",
                          marginTop: 1,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {node.detail}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
