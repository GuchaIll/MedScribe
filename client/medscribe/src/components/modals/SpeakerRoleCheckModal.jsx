import { useMemo, useState } from "react";
import PropTypes from "prop-types";
import { uploadSpeakerRoleSample } from "../../api/api";

const SAMPLE_MS = 2500;

function nextPendingRole(samples = []) {
  const captured = new Set(
    samples
      .filter((sample) => sample.status === "captured")
      .map((sample) => sample.role)
  );
  if (!captured.has("Clinician")) return "Clinician";
  if (!captured.has("Patient")) return "Patient";
  return null;
}

export default function SpeakerRoleCheckModal({ sessionId, speakerRoleCheck, onComplete, onError }) {
  const [state, setState] = useState(speakerRoleCheck);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const pendingRole = useMemo(
    () => nextPendingRole(state?.samples || []),
    [state]
  );
  const clinicianDone = (state?.samples || []).some(
    (sample) => sample.role === "Clinician" && sample.status === "captured"
  );
  const patientDone = (state?.samples || []).some(
    (sample) => sample.role === "Patient" && sample.status === "captured"
  );

  const captureSample = async () => {
    if (!sessionId || !pendingRole || busy) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      const msg = "Browser audio recording is unavailable. Use a recent Chrome, Edge, or Safari build.";
      setError(msg);
      onError?.(msg);
      return;
    }

    setBusy(true);
    setError("");
    setMessage(
      pendingRole === "Clinician"
        ? "Recording physician sample… speak naturally for 2-3 seconds."
        : "Recording patient sample… speak naturally for 2-3 seconds."
    );

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks = [];

      const result = await new Promise((resolve, reject) => {
        recorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) chunks.push(event.data);
        };
        recorder.onerror = (event) => {
          reject(event.error || new Error("Audio capture failed"));
        };
        recorder.onstop = async () => {
          try {
            const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
            const roleLabel = pendingRole === "Clinician" ? "physician" : "patient";
            const response = await uploadSpeakerRoleSample(
              sessionId,
              pendingRole,
              blob,
              `${roleLabel}-sample.webm`
            );
            resolve(response);
          } catch (uploadErr) {
            reject(uploadErr);
          }
        };

        recorder.start();
        window.setTimeout(() => {
          if (recorder.state !== "inactive") recorder.stop();
        }, SAMPLE_MS);
      });

      setState(result);
      const nextRole = nextPendingRole(result?.samples || []);
      if (!nextRole) {
        setMessage("Role check complete. Starting the live session…");
        onComplete?.(result);
      } else {
        setMessage(
          nextRole === "Patient"
            ? "Physician sample saved. Next, ask the patient to speak for 2-3 seconds."
            : ""
        );
      }
    } catch (err) {
      const msg = err?.message || "Could not capture the onboarding sample.";
      setError(msg);
      onError?.(msg);
    } finally {
      setBusy(false);
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        backgroundColor: "rgba(3,8,20,0.82)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        style={{
          width: "min(560px, 92vw)",
          borderRadius: 20,
          padding: 28,
          background:
            "linear-gradient(180deg, rgba(15,23,42,0.96) 0%, rgba(10,15,28,0.98) 100%)",
          border: "1px solid rgba(148,163,184,0.18)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.45)",
          color: "#e5eefc",
          fontFamily: "'DM Sans', sans-serif",
        }}
      >
        <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Calibrate Speaker Roles
        </div>
        <div style={{ fontSize: 14, color: "#b9c5db", lineHeight: 1.6, marginBottom: 20 }}>
          For proper speaker annotation, the physician speaks first, then the patient.
          Each person should say one short sentence so the diarization worker can map
          anonymous pyannote speakers to clinical roles.
        </div>

        <div style={{ display: "grid", gap: 10, marginBottom: 20 }}>
          <div
            style={{
              padding: 12,
              borderRadius: 12,
              backgroundColor: clinicianDone ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.04)",
              border: clinicianDone ? "1px solid rgba(34,197,94,0.35)" : "1px solid rgba(148,163,184,0.12)",
            }}
          >
            1. Physician sample {clinicianDone ? "captured" : "pending"}
          </div>
          <div
            style={{
              padding: 12,
              borderRadius: 12,
              backgroundColor: patientDone ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.04)",
              border: patientDone ? "1px solid rgba(34,197,94,0.35)" : "1px solid rgba(148,163,184,0.12)",
            }}
          >
            2. Patient sample {patientDone ? "captured" : "pending"}
          </div>
        </div>

        {message && (
          <div
            style={{
              marginBottom: 12,
              fontSize: 13,
              color: "#cdd8ef",
            }}
          >
            {message}
          </div>
        )}

        {error && (
          <div
            style={{
              marginBottom: 12,
              padding: 12,
              borderRadius: 12,
              backgroundColor: "rgba(239,68,68,0.12)",
              border: "1px solid rgba(239,68,68,0.28)",
              color: "#fecaca",
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        <button
          type="button"
          disabled={busy || !pendingRole}
          onClick={captureSample}
          style={{
            width: "100%",
            border: "none",
            borderRadius: 14,
            padding: "14px 18px",
            fontSize: 15,
            fontWeight: 700,
            color: "#04111f",
            backgroundColor: busy || !pendingRole ? "#7c8aa5" : "#7dd3fc",
            cursor: busy || !pendingRole ? "not-allowed" : "pointer",
          }}
        >
          {busy
            ? "Recording sample…"
            : pendingRole === "Clinician"
              ? "Record Physician Sample"
              : pendingRole === "Patient"
                ? "Record Patient Sample"
                : "Samples Complete"}
        </button>
      </div>
    </div>
  );
}

SpeakerRoleCheckModal.propTypes = {
  sessionId: PropTypes.string,
  speakerRoleCheck: PropTypes.shape({
    status: PropTypes.string,
    samples: PropTypes.arrayOf(
      PropTypes.shape({
        role: PropTypes.string,
        status: PropTypes.string,
      })
    ),
  }),
  onComplete: PropTypes.func,
  onError: PropTypes.func,
};
