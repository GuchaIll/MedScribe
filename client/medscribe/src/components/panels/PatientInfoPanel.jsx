import { useState, useEffect } from "react";
import { DOC_TABS, EMPTY_DOCUMENTS } from "../../constants";
import DocumentViewPanel from "../upload/DocumentViewPanel";
import PatientProfilePanel from "./PatientProfilePanel";

/* ─── Patient Info Panel ─────────────────────────────────────────────────── */
function PatientInfoPanel({ documents, uploadedFiles, onExport, structuredRecord, onSaveRecord, sessionActive, lastUpdated, pendingDocSelect, onDocSelected }) {
  const [docTab, setDocTab] = useState("Session Summary");
  const [selectedDoc, setSelectedDoc] = useState(null);
  const doc = documents[docTab] || EMPTY_DOCUMENTS[docTab];

  // Auto-select the latest uploaded document when navigating from "View Documents" button
  useEffect(() => {
    if (pendingDocSelect) {
      setDocTab("Uploaded Docs");
      const files = documents["Uploaded Docs"]?.files;
      if (files && files.length > 0) {
        setSelectedDoc(files[files.length - 1]);
      }
      onDocSelected && onDocSelected();
    }
  }, [pendingDocSelect, documents, onDocSelected]);

  // When a document entry is clicked, show the split-pane viewer
  if (selectedDoc) {
    return (
      <div style={{ height: "100%", overflow: "hidden" }}>
        <DocumentViewPanel
          doc={selectedDoc}
          structuredRecord={structuredRecord}
          onBack={() => setSelectedDoc(null)}
          onSave={onSaveRecord}
        />
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "#ffffff",
      }}
    >
      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          padding: "10px 24px 0",
          borderBottom: "1px solid rgba(0,0,0,0.07)",
          background: "#fafafa",
          overflowX: "auto",
          flexShrink: 0,
        }}
      >
        {DOC_TABS.map((t) => (
          <button
            key={t}
            onClick={() => setDocTab(t)}
            style={{
              padding: "8px 16px",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "'DM Sans', sans-serif",
              background: "transparent",
              whiteSpace: "nowrap",
              color: docTab === t ? "#1a1a1a" : "#999",
              borderBottom:
                docTab === t
                  ? "2px solid #1a1a1a"
                  : "2px solid transparent",
              transition: "all 0.18s",
              marginBottom: -1,
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "32px 48px" }}>
        {/* Header badge + export */}
        {(doc.generated || doc.badge) && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 28,
            }}
          >
            {doc.badge && (
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  padding: "3px 8px",
                  borderRadius: 4,
                  background: "rgba(0,0,0,0.06)",
                  color: "#555",
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                {doc.badge}
              </span>
            )}
            {doc.generated && (
              <span
                style={{
                  fontSize: 11,
                  color: "#aaa",
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                {doc.generated}
              </span>
            )}
            <button
              onClick={() => onExport && onExport(docTab)}
              style={{
                marginLeft: "auto",
                padding: "5px 14px",
                borderRadius: 99,
                border: "1px solid rgba(0,0,0,0.1)",
                background: "transparent",
                fontSize: 11,
                fontWeight: 600,
                color: "#666",
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(0,0,0,0.05)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
              }}
            >
              Export ↓
            </button>
          </div>
        )}

        {/* Sections */}
        {doc.sections && doc.sections.length > 0 && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 28,
            }}
          >
            {doc.sections.map((s, i) => (
              <div
                key={i}
                style={{
                  opacity: 0,
                  animation: `fadeUp 0.4s ease ${i * 0.08}s forwards`,
                }}
              >
                <div
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: "0.13em",
                    textTransform: "uppercase",
                    color: "#aaa",
                    fontFamily: "'DM Mono', monospace",
                    marginBottom: 8,
                  }}
                >
                  {s.title}
                </div>
                {s.html ? (
                  <div
                    style={{
                      fontSize: 14,
                      lineHeight: 1.78,
                      color: "#1a1a1a",
                      fontFamily: "'Lora', Georgia, serif",
                    }}
                    dangerouslySetInnerHTML={{ __html: s.html }}
                  />
                ) : (
                  <p
                    style={{
                      fontSize: 14,
                      lineHeight: 1.78,
                      color: "#1a1a1a",
                      fontFamily: "'Lora', Georgia, serif",
                      margin: 0,
                      whiteSpace: "pre-line",
                    }}
                  >
                    {s.body}
                  </p>
                )}
                {i < doc.sections.length - 1 && (
                  <div
                    style={{
                      height: 1,
                      background: "rgba(0,0,0,0.06)",
                      marginTop: 28,
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {(!doc.sections || doc.sections.length === 0) &&
          docTab !== "Uploaded Docs" &&
          docTab !== "Medical Record" && (
            <div
              style={{
                textAlign: "center",
                padding: "60px 0",
                color: "#bbb",
              }}
            >
              <p
                style={{
                  fontSize: 14,
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                No data yet — complete a transcription to generate this
                document.
              </p>
            </div>
          )}

        {/* Uploaded files */}
        {docTab === "Uploaded Docs" && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {[
              ...(doc.files || []),
              ...(uploadedFiles || []).map((f) => ({
                name: f.name,
                type: f.name.split(".").pop().toUpperCase(),
                date: "Just now",
                size: f.size
                  ? `${(f.size / 1024).toFixed(0)} KB`
                  : "—",
                status: "Uploading",
              })),
            ].map((f, i) => (
              <div
                key={i}
                onClick={() => f.status !== "Uploading" && setSelectedDoc(f)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "14px 18px",
                  borderRadius: 12,
                  border: "1px solid rgba(0,0,0,0.07)",
                  background: "#fafafa",
                  opacity: 0,
                  animation: `fadeUp 0.35s ease ${i * 0.06}s forwards`,
                  transition: "box-shadow 0.18s, background 0.15s",
                  cursor: f.status !== "Uploading" ? "pointer" : "default",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)";
                  if (f.status !== "Uploading") e.currentTarget.style.background = "#f0f4ff";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.boxShadow = "none";
                  e.currentTarget.style.background = "#fafafa";
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 8,
                      flexShrink: 0,
                      background: "rgba(0,0,0,0.06)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 9,
                      fontWeight: 700,
                      color: "#666",
                      fontFamily: "'DM Mono', monospace",
                    }}
                  >
                    {f.type}
                  </div>
                  <div>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: "#1a1a1a",
                        marginBottom: 2,
                      }}
                    >
                      {f.name}
                    </div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#aaa",
                        fontFamily: "'DM Mono', monospace",
                      }}
                    >
                      {f.documentType
                        ? `${f.documentType} · `
                        : ""}{f.date} · {f.size}
                      {f.confidence != null && f.status !== "Uploading"
                        ? ` · ${f.confidence}% confidence`
                        : ""}
                      {f.fieldsExtracted > 0
                        ? ` · ${f.fieldsExtracted} fields`
                        : ""}
                    </div>
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "3px 8px",
                      borderRadius: 4,
                      background:
                        f.status === "Reviewed" || f.status === "Processed"
                          ? "rgba(34,197,94,0.1)"
                          : f.status === "Uploading"
                          ? "rgba(59,130,246,0.1)"
                          : f.status === "Conflicts"
                          ? "rgba(239,68,68,0.1)"
                          : "rgba(234,179,8,0.1)",
                      color:
                        f.status === "Reviewed" || f.status === "Processed"
                          ? "#16a34a"
                          : f.status === "Uploading"
                          ? "#2563eb"
                          : f.status === "Conflicts"
                          ? "#dc2626"
                          : "#a16207",
                      fontFamily: "'DM Mono', monospace",
                    }}
                  >
                    {f.status}
                  </span>
                  {f.status !== "Uploading" && (
                    <span
                      style={{
                        fontSize: 16,
                        color: "#bbb",
                        lineHeight: 1,
                        userSelect: "none",
                      }}
                      title="Click to view document and consolidated record"
                    >
                      →
                    </span>
                  )}
                </div>
              </div>
            ))}
            {(!doc.files || doc.files.length === 0) &&
              (!uploadedFiles || uploadedFiles.length === 0) && (
                <div
                  style={{
                    textAlign: "center",
                    padding: "40px 0",
                    color: "#bbb",
                  }}
                >
                  <p
                    style={{
                      fontSize: 14,
                      fontFamily: "'DM Mono', monospace",
                    }}
                  >
                    No documents uploaded yet.
                  </p>
                </div>
              )}
          </div>
        )}

        {/* Medical Record Profile */}
        {docTab === "Medical Record" && (
          <PatientProfilePanel
            structuredRecord={structuredRecord}
            sessionActive={sessionActive}
            lastUpdated={lastUpdated}
          />
        )}
      </div>
    </div>
  );
}

export default PatientInfoPanel;
