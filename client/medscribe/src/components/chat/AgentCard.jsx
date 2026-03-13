import { useState } from "react";
import { CHANGE_COLORS } from "../../constants";

/* ─── Agent message card (session summary / record review) ───────────────── */
function AgentCard({ msg, visible, onApprove, onSwitchTab }) {
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  return (
    <div
      style={{
        display: "flex",
        gap: 11,
        alignItems: "flex-start",
        maxWidth: 640,
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(16px)",
        transition: "opacity 0.42s ease, transform 0.42s ease",
      }}
    >
      {/* Agent avatar */}
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          flexShrink: 0,
          background:
            "linear-gradient(135deg, #c7d2fe 0%, #ddd6fe 50%, #e9d5ff 100%)",
          border: "2px solid #a5b4fc",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 17,
          boxShadow: "0 2px 8px rgba(139,92,246,0.18)",
        }}
      >
        🤖
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 5,
          minWidth: 0,
          flex: 1,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#6d28d9",
              letterSpacing: "-0.01em",
            }}
          >
            MedScribe Agent
          </span>
          <span
            style={{
              fontSize: 9,
              padding: "1px 6px",
              borderRadius: 4,
              background: "#ede9fe",
              color: "#7c3aed",
              fontWeight: 700,
              fontFamily: "'DM Mono', monospace",
              letterSpacing: "0.06em",
            }}
          >
            AI
          </span>
          <span
            style={{
              fontSize: 10,
              color: "#a0a0b0",
              fontFamily: "'DM Mono', monospace",
            }}
          >
            {msg.time}
          </span>
        </div>

        {/* Card body — pastel lavender background */}
        <div
          style={{
            padding: "18px 22px",
            borderRadius: "4px 18px 18px 18px",
            background:
              "linear-gradient(135deg, #f0ecff 0%, #e8f4fd 50%, #fdf2f8 100%)",
            border: "1px solid #c7d2fe",
            boxShadow:
              "0 3px 16px rgba(139,92,246,0.10), 0 1px 3px rgba(139,92,246,0.06), inset 0 1px 0 rgba(255,255,255,0.95)",
          }}
        >
          {/* ── Summary card ── */}
          {msg.cardType === "summary" && (
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "linear-gradient(135deg, #a78bfa, #818cf8)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 14,
                    boxShadow: "0 2px 6px rgba(139,92,246,0.2)",
                  }}
                >
                  📋
                </div>
                <span
                  style={{ fontSize: 14, fontWeight: 700, color: "#1e1b4b" }}
                >
                  Session Complete
                </span>
              </div>

              {/* Stats row */}
              {msg.stats && (
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    marginBottom: 14,
                    flexWrap: "wrap",
                  }}
                >
                  {msg.stats.map((s, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "8px 14px",
                        borderRadius: 10,
                        background: "rgba(255,255,255,0.7)",
                        border: "1px solid rgba(139,92,246,0.12)",
                        minWidth: 70,
                        textAlign: "center",
                      }}
                    >
                      <div
                        style={{
                          fontSize: 18,
                          fontWeight: 800,
                          color: "#4c1d95",
                          fontFamily: "'DM Mono', monospace",
                        }}
                      >
                        {s.value}
                      </div>
                      <div
                        style={{
                          fontSize: 9,
                          color: "#7c3aed",
                          fontFamily: "'DM Mono', monospace",
                          textTransform: "uppercase",
                          letterSpacing: "0.08em",
                          marginTop: 2,
                        }}
                      >
                        {s.label}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Clinical alerts */}
              {msg.clinicalAlerts && msg.clinicalAlerts.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  {msg.clinicalAlerts.map((alert, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 7,
                        padding: "6px 12px",
                        marginBottom: 4,
                        borderRadius: 8,
                        background:
                          alert.level === "critical" || alert.level === "high"
                            ? "rgba(239,68,68,0.08)"
                            : alert.level === "moderate"
                            ? "rgba(234,179,8,0.08)"
                            : "rgba(34,197,94,0.06)",
                        border:
                          alert.level === "critical" || alert.level === "high"
                            ? "1px solid rgba(239,68,68,0.18)"
                            : alert.level === "moderate"
                            ? "1px solid rgba(234,179,8,0.18)"
                            : "1px solid rgba(34,197,94,0.12)",
                      }}
                    >
                      <span style={{ fontSize: 12 }}>
                        {alert.level === "critical" || alert.level === "high"
                          ? "⚠️"
                          : alert.level === "moderate"
                          ? "⚡"
                          : "✓"}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: "#444",
                          fontFamily: "'DM Sans', sans-serif",
                        }}
                      >
                        {alert.text}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Summary text or generated HTML */}
              {msg.summaryHtml ? (
                <div
                  style={{
                    fontSize: 13,
                    lineHeight: 1.72,
                    color: "#374151",
                    fontFamily: "'Lora', Georgia, serif",
                    marginBottom: 14,
                    maxHeight: 220,
                    overflowY: "auto",
                    padding: "12px 14px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.6)",
                    border: "1px solid rgba(139,92,246,0.08)",
                  }}
                  dangerouslySetInnerHTML={{ __html: msg.summaryHtml }}
                />
              ) : msg.text ? (
                <p
                  style={{
                    fontSize: 13,
                    lineHeight: 1.72,
                    color: "#374151",
                    fontFamily: "'Lora', Georgia, serif",
                    margin: "0 0 14px",
                  }}
                >
                  {msg.text}
                </p>
              ) : null}

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  onClick={() =>
                    onSwitchTab && onSwitchTab("Patient Info")
                  }
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "8px 18px",
                    borderRadius: 99,
                    background:
                      "linear-gradient(135deg, #818cf8, #6d28d9)",
                    border: "none",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    transition: "all 0.18s",
                    boxShadow: "0 2px 8px rgba(109,40,217,0.25)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-1px)";
                    e.currentTarget.style.boxShadow =
                      "0 4px 14px rgba(109,40,217,0.35)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.boxShadow =
                      "0 2px 8px rgba(109,40,217,0.25)";
                  }}
                >
                  📄 View Discharge Note
                </button>
              </div>
            </div>
          )}

          {/* ── Record review card ── */}
          {msg.cardType === "review" && (
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  marginBottom: 8,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background:
                      "linear-gradient(135deg, #fbbf24, #f59e0b)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 14,
                    boxShadow: "0 2px 6px rgba(245,158,11,0.2)",
                  }}
                >
                  🔍
                </div>
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: "#1e1b4b",
                  }}
                >
                  Review Patient Record Changes
                </span>
              </div>
              <p
                style={{
                  fontSize: 12,
                  lineHeight: 1.6,
                  color: "#6b7280",
                  margin: "0 0 14px",
                  fontFamily: "'DM Sans', sans-serif",
                }}
              >
                The following fields were modified during this session.
                Please review each change and approve when ready.
              </p>

              {/* Legend */}
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  marginBottom: 14,
                  flexWrap: "wrap",
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: "rgba(255,255,255,0.5)",
                  border: "1px solid rgba(139,92,246,0.08)",
                }}
              >
                {["ok", "warning", "conflict", "unchanged"].map((k) => (
                  <div
                    key={k}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                    }}
                  >
                    <div
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: CHANGE_COLORS[k].dot,
                      }}
                    />
                    <span
                      style={{
                        fontSize: 10,
                        color: "#6b7280",
                        fontFamily: "'DM Mono', monospace",
                      }}
                    >
                      {CHANGE_COLORS[k].label}
                    </span>
                  </div>
                ))}
              </div>

              {/* Field list */}
              <div
                style={{
                  maxHeight: 420,
                  overflowY: "auto",
                  paddingRight: 4,
                }}
              >
                {msg.fields &&
                  msg.fields.map((f, i) => {
                    const c =
                      CHANGE_COLORS[f.status] || CHANGE_COLORS.unchanged;
                    return (
                      <div
                        key={i}
                        style={{
                          padding: "10px 14px",
                          marginBottom: 6,
                          borderRadius: 10,
                          background: c.bg,
                          border: `1.5px solid ${c.border}`,
                          transition: "all 0.2s",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            marginBottom: 4,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            <div
                              style={{
                                width: 7,
                                height: 7,
                                borderRadius: "50%",
                                background: c.dot,
                                flexShrink: 0,
                              }}
                            />
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 700,
                                textTransform: "uppercase",
                                letterSpacing: "0.1em",
                                color: "#4b5563",
                                fontFamily: "'DM Mono', monospace",
                              }}
                            >
                              {f.title}
                            </span>
                          </div>
                          <span
                            style={{
                              fontSize: 9,
                              fontWeight: 700,
                              padding: "2px 7px",
                              borderRadius: 4,
                              background: c.bg,
                              color: c.dot,
                              fontFamily: "'DM Mono', monospace",
                              textTransform: "uppercase",
                              letterSpacing: "0.06em",
                              border: `1px solid ${c.border}`,
                            }}
                          >
                            {c.label}
                          </span>
                        </div>
                        <p
                          style={{
                            fontSize: 13,
                            lineHeight: 1.65,
                            color: "#1e1b4b",
                            margin: 0,
                            fontFamily: "'Lora', Georgia, serif",
                            whiteSpace: "pre-line",
                          }}
                        >
                          {f.value}
                        </p>
                        {f.reason && (
                          <p
                            style={{
                              fontSize: 11,
                              color: "#7c3aed",
                              margin: "4px 0 0",
                              fontFamily: "'DM Sans', sans-serif",
                              fontStyle: "italic",
                            }}
                          >
                            ℹ {f.reason}
                          </p>
                        )}
                      </div>
                    );
                  })}
              </div>

              {/* Approve button */}
              {!msg.approved && (
                <button
                  onClick={() => onApprove && onApprove(msg.id)}
                  style={{
                    marginTop: 14,
                    width: "100%",
                    padding: "11px 20px",
                    borderRadius: 12,
                    background:
                      "linear-gradient(135deg, #22c55e 0%, #16a34a 100%)",
                    border: "none",
                    color: "#fff",
                    fontSize: 13,
                    fontWeight: 700,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    boxShadow: "0 3px 14px rgba(34,197,94,0.3)",
                    transition: "all 0.18s",
                    letterSpacing: "0.02em",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-1px)";
                    e.currentTarget.style.boxShadow =
                      "0 5px 22px rgba(34,197,94,0.4)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.boxShadow =
                      "0 3px 14px rgba(34,197,94,0.3)";
                  }}
                >
                  ✓ Approve Changes
                </button>
              )}
              {msg.approved && (
                <div
                  style={{
                    marginTop: 14,
                    padding: "11px 16px",
                    borderRadius: 12,
                    background:
                      "linear-gradient(135deg, rgba(34,197,94,0.12), rgba(16,185,129,0.08))",
                    border: "1px solid rgba(34,197,94,0.25)",
                    textAlign: "center",
                  }}
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: "#16a34a",
                      fontFamily: "'DM Sans', sans-serif",
                    }}
                  >
                    ✓ Changes Approved — Record Updated
                  </span>
                </div>
              )}
            </div>
          )}

          {/* ── Document analysis card ── */}
          {msg.cardType === "document" && (
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "linear-gradient(135deg, #60a5fa, #3b82f6)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 14,
                    boxShadow: "0 2px 6px rgba(59,130,246,0.2)",
                  }}
                >
                  📄
                </div>
                <span
                  style={{ fontSize: 14, fontWeight: 700, color: "#1e1b4b" }}
                >
                  Document Analyzed
                </span>
                {msg.docType && (
                  <span
                    style={{
                      fontSize: 9,
                      padding: "2px 7px",
                      borderRadius: 4,
                      background: "rgba(59,130,246,0.12)",
                      color: "#2563eb",
                      fontWeight: 700,
                      fontFamily: "'DM Mono', monospace",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    {msg.docType}
                  </span>
                )}
              </div>

              {/* Stats row */}
              {msg.stats && (
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    marginBottom: 14,
                    flexWrap: "wrap",
                  }}
                >
                  {msg.stats.map((s, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "8px 14px",
                        borderRadius: 10,
                        background: "rgba(255,255,255,0.7)",
                        border: "1px solid rgba(59,130,246,0.12)",
                        minWidth: 70,
                        textAlign: "center",
                      }}
                    >
                      <div
                        style={{
                          fontSize: 18,
                          fontWeight: 800,
                          color: "#1e40af",
                          fontFamily: "'DM Mono', monospace",
                        }}
                      >
                        {s.value}
                      </div>
                      <div
                        style={{
                          fontSize: 9,
                          color: "#3b82f6",
                          fontFamily: "'DM Mono', monospace",
                          textTransform: "uppercase",
                          letterSpacing: "0.08em",
                          marginTop: 2,
                        }}
                      >
                        {s.label}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Agent summary text */}
              {msg.text && (
                <p
                  style={{
                    fontSize: 13,
                    lineHeight: 1.72,
                    color: "#374151",
                    fontFamily: "'Lora', Georgia, serif",
                    margin: "0 0 14px",
                    padding: "12px 14px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.6)",
                    border: "1px solid rgba(59,130,246,0.08)",
                    whiteSpace: "pre-line",
                  }}
                >
                  {msg.text}
                </p>
              )}

              {/* Extracted field changes */}
              {msg.fieldChanges && msg.fieldChanges.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                      color: "#6b7280",
                      fontFamily: "'DM Mono', monospace",
                      marginBottom: 8,
                    }}
                  >
                    Extracted Fields
                  </div>
                  <div
                    style={{
                      maxHeight: 300,
                      overflowY: "auto",
                      paddingRight: 4,
                    }}
                  >
                    {msg.fieldChanges.map((fc, i) => {
                      const isLow = fc.confidence < 0.5;
                      const c = isLow
                        ? CHANGE_COLORS.warning
                        : CHANGE_COLORS.ok;
                      return (
                        <div
                          key={i}
                          style={{
                            padding: "8px 12px",
                            marginBottom: 5,
                            borderRadius: 8,
                            background: c.bg,
                            border: `1px solid ${c.border}`,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              marginBottom: 3,
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                              }}
                            >
                              <div
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: c.dot,
                                  flexShrink: 0,
                                }}
                              />
                              <span
                                style={{
                                  fontSize: 10,
                                  fontWeight: 700,
                                  textTransform: "uppercase",
                                  letterSpacing: "0.08em",
                                  color: "#4b5563",
                                  fontFamily: "'DM Mono', monospace",
                                }}
                              >
                                {fc.field_name}
                              </span>
                            </div>
                            <span
                              style={{
                                fontSize: 9,
                                fontWeight: 700,
                                padding: "1px 6px",
                                borderRadius: 3,
                                background: "rgba(255,255,255,0.6)",
                                color: isLow ? "#a16207" : "#16a34a",
                                fontFamily: "'DM Mono', monospace",
                              }}
                            >
                              {Math.round(fc.confidence * 100)}%
                            </span>
                          </div>
                          <p
                            style={{
                              fontSize: 12,
                              lineHeight: 1.5,
                              color: "#1e1b4b",
                              margin: 0,
                              fontFamily: "'Lora', Georgia, serif",
                              wordBreak: "break-word",
                            }}
                          >
                            {fc.value.length > 120
                              ? fc.value.slice(0, 120) + "…"
                              : fc.value}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Conflict alerts */}
              {msg.conflictDetails && msg.conflictDetails.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                      color: "#6b7280",
                      fontFamily: "'DM Mono', monospace",
                      marginBottom: 8,
                    }}
                  >
                    Conflicts Detected
                  </div>
                  {msg.conflictDetails.map((cd, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 7,
                        padding: "6px 12px",
                        marginBottom: 4,
                        borderRadius: 8,
                        background:
                          cd.severity === "critical" || cd.severity === "high"
                            ? "rgba(239,68,68,0.08)"
                            : "rgba(234,179,8,0.08)",
                        border:
                          cd.severity === "critical" || cd.severity === "high"
                            ? "1px solid rgba(239,68,68,0.18)"
                            : "1px solid rgba(234,179,8,0.18)",
                      }}
                    >
                      <span style={{ fontSize: 12, flexShrink: 0 }}>
                        {cd.severity === "critical" || cd.severity === "high"
                          ? "⚠️"
                          : "⚡"}
                      </span>
                      <div>
                        <span
                          style={{
                            fontSize: 10,
                            fontWeight: 700,
                            color: "#4b5563",
                            fontFamily: "'DM Mono', monospace",
                            textTransform: "uppercase",
                          }}
                        >
                          {cd.field_name}
                        </span>
                        <p
                          style={{
                            fontSize: 11,
                            color: "#444",
                            margin: "2px 0 0",
                            fontFamily: "'DM Sans', sans-serif",
                          }}
                        >
                          {cd.message}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  onClick={() =>
                    onSwitchTab && onSwitchTab("Uploaded Docs")
                  }
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "8px 18px",
                    borderRadius: 99,
                    background:
                      "linear-gradient(135deg, #60a5fa, #3b82f6)",
                    border: "none",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    transition: "all 0.18s",
                    boxShadow: "0 2px 8px rgba(59,130,246,0.25)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-1px)";
                    e.currentTarget.style.boxShadow =
                      "0 4px 14px rgba(59,130,246,0.35)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.boxShadow =
                      "0 2px 8px rgba(59,130,246,0.25)";
                  }}
                >
                  📂 View Documents
                </button>
              </div>
            </div>
          )}

          {/* ── Assistant loading card ── */}
          {msg.cardType === "assistant_loading" && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 8,
                  background: "linear-gradient(135deg, #a78bfa, #818cf8)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                }}
              >
                🔍
              </div>
              <span
                style={{
                  fontSize: 13,
                  color: "#6d28d9",
                  fontFamily: "'DM Sans', sans-serif",
                  fontStyle: "italic",
                }}
                className="blink"
              >
                {msg.text}
              </span>
            </div>
          )}

          {/* ── Assistant response card ── */}
          {msg.cardType === "assistant_response" && (
            <div>
              {/* Header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  marginBottom: 10,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: "linear-gradient(135deg, #a78bfa, #6d28d9)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 14,
                    boxShadow: "0 2px 6px rgba(109,40,217,0.2)",
                  }}
                >
                  💬
                </div>
                <span
                  style={{ fontSize: 14, fontWeight: 700, color: "#1e1b4b" }}
                >
                  Assistant Response
                </span>
                {/* Confidence badge — shown when low */}
                {msg.lowConfidence && typeof msg.confidence === "number" && (
                  <span
                    style={{
                      fontSize: 9,
                      padding: "2px 7px",
                      borderRadius: 4,
                      background: "rgba(234,179,8,0.14)",
                      color: "#a16207",
                      fontWeight: 700,
                      fontFamily: "'DM Mono', monospace",
                      letterSpacing: "0.06em",
                      border: "1px solid rgba(234,179,8,0.28)",
                    }}
                  >
                    Confidence: {Math.round(msg.confidence * 100)}%
                  </span>
                )}
              </div>

              {/* Doctor's question (italic) */}
              {msg.question && (
                <p
                  style={{
                    fontSize: 12,
                    lineHeight: 1.6,
                    color: "#6b7280",
                    margin: "0 0 10px",
                    fontFamily: "'DM Sans', sans-serif",
                    fontStyle: "italic",
                  }}
                >
                  Q: {msg.question}
                </p>
              )}

              {/* Answer */}
              <p
                style={{
                  fontSize: 13,
                  lineHeight: 1.72,
                  color: msg.confidence === 0 ? "#9ca3af" : "#1e1b4b",
                  margin: "0 0 10px",
                  fontFamily: "'Lora', Georgia, serif",
                  padding: "12px 14px",
                  borderRadius: 10,
                  background:
                    msg.confidence === 0
                      ? "rgba(156,163,175,0.08)"
                      : "rgba(255,255,255,0.65)",
                  border:
                    msg.confidence === 0
                      ? "1px solid rgba(156,163,175,0.18)"
                      : "1px solid rgba(139,92,246,0.08)",
                  whiteSpace: "pre-line",
                }}
              >
                {msg.answer}
              </p>

              {/* Low-confidence disclaimer */}
              {msg.disclaimer && (
                <p
                  style={{
                    fontSize: 11,
                    lineHeight: 1.6,
                    color: "#a16207",
                    margin: "0 0 10px",
                    fontFamily: "'DM Sans', sans-serif",
                    fontStyle: "italic",
                    padding: "8px 12px",
                    borderRadius: 8,
                    background: "rgba(234,179,8,0.07)",
                    border: "1px solid rgba(234,179,8,0.2)",
                  }}
                >
                  ⚠ {msg.disclaimer}
                </p>
              )}

              {/* Sources (collapsible) */}
              {msg.sources && msg.sources.length > 0 && (
                <div>
                  <div
                    onClick={() => setSourcesExpanded((e) => !e)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      cursor: "pointer",
                      userSelect: "none",
                      marginBottom: sourcesExpanded ? 8 : 0,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        color: "#7c3aed",
                        fontFamily: "'DM Mono', monospace",
                        fontStyle: "italic",
                      }}
                    >
                      {sourcesExpanded
                        ? "▾ hide sources"
                        : `▸ ${msg.sources.length} source${msg.sources.length !== 1 ? "s" : ""}`}
                    </span>
                  </div>
                  {sourcesExpanded && (
                    <div
                      style={{
                        maxHeight: 180,
                        overflowY: "auto",
                        paddingRight: 4,
                      }}
                    >
                      {msg.sources.map((src, i) => (
                        <div
                          key={i}
                          style={{
                            padding: "7px 10px",
                            marginBottom: 4,
                            borderRadius: 7,
                            background: "rgba(255,255,255,0.55)",
                            border: "1px solid rgba(139,92,246,0.10)",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              marginBottom: 3,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 9,
                                fontWeight: 700,
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                                color: "#6d28d9",
                                fontFamily: "'DM Mono', monospace",
                              }}
                            >
                              {src.type || src.fact_type || "source"}
                            </span>
                            <span
                              style={{
                                fontSize: 9,
                                fontFamily: "'DM Mono', monospace",
                                color:
                                  src.similarity >= 0.65
                                    ? "#16a34a"
                                    : "#a16207",
                              }}
                            >
                              {Math.round((src.similarity || 0) * 100)}%
                            </span>
                          </div>
                          <p
                            style={{
                              fontSize: 11,
                              color: "#374151",
                              margin: 0,
                              fontFamily: "'Lora', Georgia, serif",
                              lineHeight: 1.5,
                              wordBreak: "break-word",
                            }}
                          >
                            {src.snippet || "—"}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentCard;
