import GlassPanel from "../ui/GlassPanel";
import { prepareUpload } from "../../api/api";

export default function UploadPanel({
  onClose,
  uploadedFiles,
  setUploadedFiles,
  onUpload,
  fileInputRef,
}) {
  return (
    <div
      className="fadeUp"
      style={{
        position: "fixed",
        bottom: 172,
        right: 28,
        width: 310,
        zIndex: 40,
      }}
    >
      <GlassPanel
        style={{
          borderRadius: 16,
          padding: 18,
          boxShadow:
            "0 20px 60px rgba(0,0,0,0.55), 0 4px 16px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 14,
          }}
        >
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.13em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.4)",
              fontFamily: "'DM Mono', monospace",
            }}
          >
            Upload Document
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "rgba(255,255,255,0.25)",
              fontSize: 14,
            }}
          >
            ✕
          </button>
        </div>

        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            e.currentTarget.style.background = "rgba(255,255,255,0.1)";
            e.currentTarget.style.borderColor = "rgba(255,255,255,0.3)";
          }}
          onDragLeave={(e) => {
            e.currentTarget.style.background = "rgba(255,255,255,0.04)";
            e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.currentTarget.style.background = "rgba(255,255,255,0.04)";
            e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
            const files = Array.from(e.dataTransfer.files);
            setUploadedFiles((p) => [...p, ...files.map(prepareUpload)]);
          }}
          style={{
            border: "1.5px dashed rgba(255,255,255,0.1)",
            borderRadius: 10,
            padding: "20px 16px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 8,
            cursor: "pointer",
            background: "rgba(255,255,255,0.04)",
            transition: "all 0.18s",
          }}
        >
          <span style={{ fontSize: 22, opacity: 0.5 }}>⬆</span>
          <span
            style={{
              fontSize: 12,
              color: "rgba(255,255,255,0.5)",
              fontWeight: 500,
              textAlign: "center",
              lineHeight: 1.5,
            }}
          >
            Click or drag files here
          </span>
          <span
            style={{
              fontSize: 10,
              color: "rgba(255,255,255,0.22)",
              fontFamily: "'DM Mono', monospace",
              textAlign: "center",
            }}
          >
            PDF · DOCX · JPG · PNG · DICOM
          </span>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff,.dicom,.dcm"
          style={{ display: "none" }}
          onChange={(e) => {
            const files = Array.from(e.target.files);
            setUploadedFiles((p) => [...p, ...files.map(prepareUpload)]);
            e.target.value = "";
          }}
        />

        {uploadedFiles.length > 0 && (
          <div
            style={{
              marginTop: 12,
              display: "flex",
              flexDirection: "column",
              gap: 5,
            }}
          >
            {uploadedFiles.map((f, i) => {
              const ext = f.name.split(".").pop().toUpperCase();
              const kb = (f.size / 1024).toFixed(1);
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "7px 10px",
                    borderRadius: 8,
                    background: "rgba(255,255,255,0.06)",
                    border: "1px solid rgba(255,255,255,0.08)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      minWidth: 0,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 9,
                        fontWeight: 700,
                        padding: "2px 5px",
                        borderRadius: 4,
                        background: "rgba(255,255,255,0.1)",
                        color: "rgba(255,255,255,0.55)",
                        fontFamily: "'DM Mono', monospace",
                        flexShrink: 0,
                      }}
                    >
                      {ext}
                    </span>
                    <span
                      style={{
                        fontSize: 11,
                        color: "rgba(255,255,255,0.7)",
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {f.name}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      flexShrink: 0,
                      marginLeft: 8,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        color: "rgba(255,255,255,0.28)",
                        fontFamily: "'DM Mono', monospace",
                      }}
                    >
                      {kb}kb
                    </span>
                    <button
                      onClick={() =>
                        setUploadedFiles((p) => p.filter((_, j) => j !== i))
                      }
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        color: "rgba(255,255,255,0.22)",
                        fontSize: 12,
                        lineHeight: 1,
                        padding: 0,
                      }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {uploadedFiles.length > 0 && (
          <button
            onClick={onUpload}
            style={{
              marginTop: 10,
              width: "100%",
              padding: 8,
              borderRadius: 8,
              background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.1)",
              color: "rgba(255,255,255,0.75)",
              fontWeight: 600,
              fontSize: 12,
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "background 0.18s",
            }}
          >
            Upload & Analyze ({uploadedFiles.length})
          </button>
        )}
      </GlassPanel>
    </div>
  );
}
