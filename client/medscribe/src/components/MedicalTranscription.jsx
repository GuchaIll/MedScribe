import { useState, useEffect, useRef, useCallback } from "react";
import {
  startSession,
  endSession,
  sendTranscription,
  runPipeline,
  generateRecord,
  getClinicalSuggestions,
  uploadDocuments,
  askAssistant,
  speakText,
} from "../api/api";

import Toast from "./ui/Toast";
import PatientInfoPanel from "./panels/PatientInfoPanel";

import AppHeader from "./layout/AppHeader";
import Sidebar from "./layout/Sidebar";
import Footer from "./layout/Footer";
import TranscriptionFeed from "./transcription/TranscriptionFeed";
import UploadPanel from "./upload/UploadPanel";

import useTimer from "../hooks/useTimer";
import useNotify from "../hooks/useNotify";
import useVoiceCapture from "../hooks/useVoiceCapture";

import { PHYSICIAN, PATIENT, AGENT, PIPELINE_STEPS, EMPTY_DOCUMENTS } from "../constants";

const ASSISTANT_REGEX = /^assistant[,:\s]+(.+)/i;
const PATIENT_ID = "patient-default-001";

export default function MedicalTranscription() {
  /* ── Session ── */
  const [sessionId, setSessionId] = useState(null);
  const [sessionActive, setSessionActive] = useState(false);

  /* ── Messages / transcript ── */
  const [msgs, setMsgs] = useState([]);
  const [vis, setVis] = useState(new Set());
  const nextIdRef = useRef(1);

  /* ── UI ── */
  const [tab, setTab] = useState("Transcription");
  const [muted, setMuted] = useState(false);
  const [recording, setRecording] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const fileInputRef = useRef(null);
  const [pipelineStep, setPipelineStep] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [demoText, setDemoText] = useState("");
  const feedRef = useRef(null);
  const timer = useTimer();

  /* ── Pipeline output ── */
  const [pipelineResult, setPipelineResult] = useState(null);
  const [documents, setDocuments] = useState(EMPTY_DOCUMENTS);
  const [pipelineRunning, setPipelineRunning] = useState(false);

  /* ── Notifications ── */
  const { toast, notify, clearToast } = useNotify();

  /* ── Segments for pipeline ── */
  const segmentsRef = useRef([]);

  /* ── Stable timer ref (avoids recreating addUtterance every tick) ── */
  const timerSecondsRef = useRef(0);
  useEffect(() => {
    timerSecondsRef.current = timer.seconds;
  }, [timer.seconds]);

  /* ── Stable ref to handleAssistantQuery (avoids stale closure in addUtterance) ── */
  const handleAssistantQueryRef = useRef(null);

  /* ── Auto-scroll feed ── */
  useEffect(() => {
    if (feedRef.current)
      feedRef.current.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  /* ── Pipeline step animation ── */
  useEffect(() => {
    if (!transcribing) return;
    const id = setInterval(
      () => setPipelineStep((s) => (s + 1) % PIPELINE_STEPS.length),
      1100
    );
    return () => clearInterval(id);
  }, [transcribing]);

  /* ── Start Session ── */
  const handleStartSession = useCallback(async () => {
    try {
      const res = await startSession();
      setSessionId(res.session_id);
      setSessionActive(true);
      setMsgs([]);
      setVis(new Set());
      nextIdRef.current = 1;
      segmentsRef.current = [];
      setPipelineResult(null);
      setDocuments(EMPTY_DOCUMENTS);
      setRecording(true);
      setTranscribing(true);
      timer.reset();
      timer.start();
      notify(`Session started: ${res.session_id.slice(0, 8)}…`, "success");
    } catch (err) {
      notify(`Failed to start session: ${err.message}`, "error");
    }
  }, [notify, timer]);

  /* ── Send utterance to backend ── */
  const addUtterance = useCallback(
    async (text, speaker = "Unknown") => {
      if (!sessionId || !text.trim()) return;

      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const speakerObj = speaker.toLowerCase().includes("patient") ? PATIENT : PHYSICIAN;

      const id = nextIdRef.current++;
      const localMsg = { id, speaker: speakerObj, time: timeStr, text, pipeline: [] };
      setMsgs((prev) => [...prev, localMsg]);
      setTimeout(() => setVis((prev) => new Set([...prev, id])), 100);

      const elapsed = timerSecondsRef.current;
      segmentsRef.current.push({
        start: Math.max(0, elapsed - 5),
        end: elapsed,
        speaker: speakerObj.role,
        raw_text: text,
      });

      const assistantMatch = text.trim().match(ASSISTANT_REGEX);
      if (assistantMatch && handleAssistantQueryRef.current) {
        handleAssistantQueryRef.current(assistantMatch[1].trim());
      }

      try {
        const res = await sendTranscription(sessionId, text, speakerObj.role);
        const pipelineFeedback = [
          { label: `Speaker: ${res.speaker}`, state: "done" },
          { label: `Source: ${res.source}`, state: "done" },
        ];
        if (res.agent_message) pipelineFeedback.push({ label: res.agent_message, state: "done" });
        setMsgs((prev) =>
          prev.map((m) => (m.id === id ? { ...m, pipeline: pipelineFeedback } : m))
        );
      } catch (err) {
        console.error("Transcription send failed:", err);
        setMsgs((prev) =>
          prev.map((m) =>
            m.id === id
              ? { ...m, pipeline: [{ label: `Error: ${err.message}`, state: "error" }] }
              : m
          )
        );
      }
    },
    [sessionId]
  );

  /* ── Assistant Q&A ── */
  const handleAssistantQuery = useCallback(
    async (question) => {
      if (!sessionId) return;

      const loadingId = nextIdRef.current++;
      const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setMsgs((prev) => [
        ...prev,
        { id: loadingId, speaker: AGENT, time: timeStr, cardType: "assistant_loading", text: "Looking up patient records…" },
      ]);
      setTimeout(() => setVis((prev) => new Set([...prev, loadingId])), 100);

      try {
        const response = await askAssistant(sessionId, PATIENT_ID, question);
        setMsgs((prev) =>
          prev.map((m) =>
            m.id === loadingId
              ? {
                  ...m,
                  cardType: "assistant_response",
                  question,
                  answer: response.answer,
                  confidence: response.confidence,
                  lowConfidence: response.low_confidence,
                  disclaimer: response.disclaimer,
                  sources: response.sources || [],
                }
              : m
          )
        );
        await speakText(response.answer);
      } catch (err) {
        console.error("Assistant query failed:", err);
        setMsgs((prev) =>
          prev.map((m) =>
            m.id === loadingId
              ? {
                  ...m,
                  cardType: "assistant_response",
                  question,
                  answer: "I was unable to retrieve the patient records at this time. Please consult the chart directly.",
                  confidence: 0,
                  lowConfidence: true,
                  disclaimer: null,
                  sources: [],
                }
              : m
          )
        );
      }
    },
    [sessionId]
  );

  handleAssistantQueryRef.current = handleAssistantQuery;

  /* ── Helpers: field classification for record review ── */
  const classifyField = useCallback((title, value, validation) => {
    if (validation) {
      const titleLower = title.toLowerCase();
      const conflicts = validation.contradictions || validation.conflicts || [];
      const warnings = validation.warnings || [];
      const hasConflict = conflicts.some((c) =>
        (typeof c === "string" ? c : c.field || c.message || "").toLowerCase().includes(titleLower)
      );
      if (hasConflict) return "conflict";
      const hasWarning = warnings.some((w) =>
        (typeof w === "string" ? w : w.field || w.message || "").toLowerCase().includes(titleLower)
      );
      if (hasWarning) return "warning";
    }
    if (value && String(value).trim()) return "ok";
    return "unchanged";
  }, []);

  const buildReviewFields = useCallback(
    (record, validation) => {
      const fields = [];
      const add = (title, raw) => {
        let value = "";
        if (raw == null) {
          value = "—";
        } else if (typeof raw === "string") {
          value = raw;
        } else if (Array.isArray(raw)) {
          value = raw
            .map((item) =>
              typeof item === "string" ? item : item.name || item.substance || JSON.stringify(item)
            )
            .join("\n");
        } else {
          value = JSON.stringify(raw, null, 2);
        }
        const status = classifyField(title, raw, validation);
        const reason =
          status === "conflict"
            ? "Conflicts with existing record — please verify"
            : status === "warning"
            ? "Low confidence — please confirm"
            : status === "ok"
            ? "Updated from session transcript"
            : null;
        fields.push({ title, value, status, reason });
      };

      if (record.patient_info) add("Patient Info", record.patient_info);
      add("Chief Complaint", record.chief_complaint);
      add("History of Present Illness", record.history_of_present_illness);
      add("Medications", record.medications);
      add("Allergies", record.allergies);
      add("Assessment", record.assessment);
      add("Plan", record.plan);
      if (record.vitals) add("Vitals", record.vitals);
      if (record.physical_exam) add("Physical Exam", record.physical_exam);
      if (record.diagnosis) add("Diagnosis", record.diagnosis);
      if (record.follow_up) add("Follow-Up", record.follow_up);

      return fields;
    },
    [classifyField]
  );

  /* ── Complete Transcription (run pipeline → end session → agent messages) ── */
  const handleCompleteTranscription = useCallback(async () => {
    if (speech.flush) speech.flush();

    if (!sessionId || segmentsRef.current.length === 0) {
      notify("No transcript segments to process", "error");
      return;
    }

    setPipelineRunning(true);
    setTranscribing(false);
    setRecording(false);
    timer.stop();
    notify("Running pipeline…", "info");

    try {
      const result = await runPipeline(
        sessionId,
        "patient-default-001",
        "doctor-default-001",
        segmentsRef.current
      );
      setPipelineResult(result);

      try {
        await endSession(sessionId);
      } catch (e) {
        console.warn("End session call failed:", e);
      }
      setSessionActive(false);

      let clinicalData = result.clinical_suggestions || null;
      if (result.structured_record) {
        try {
          clinicalData = await getClinicalSuggestions(result.structured_record);
        } catch (e) {
          console.warn("Clinical suggestions fetch failed, using pipeline data:", e);
        }
      }

      const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const newDocs = { ...EMPTY_DOCUMENTS };

      let soapHtml = null;
      if (result.structured_record) {
        try {
          soapHtml = await generateRecord(result.structured_record, "soap", "html", clinicalData);
          newDocs["Session Summary"] = {
            generated: `Today, ${now}`,
            badge: "Auto-generated",
            sections: [{ title: "SOAP Note", html: soapHtml }],
          };
        } catch (e) {
          console.warn("SOAP generation failed, falling back to clinical_note:", e);
        }
      }
      if (!newDocs["Session Summary"].generated && result.clinical_note) {
        newDocs["Session Summary"] = {
          generated: `Today, ${now}`,
          badge: "Auto-generated",
          sections: [{ title: "Clinical Note", body: result.clinical_note }],
        };
      }

      if (result.structured_record) {
        const rec = result.structured_record;
        const sections = [];
        if (rec.patient_info)
          sections.push({
            title: "Patient",
            body: typeof rec.patient_info === "string" ? rec.patient_info : JSON.stringify(rec.patient_info, null, 2),
          });
        if (rec.chief_complaint) sections.push({ title: "Chief Complaint", body: rec.chief_complaint });
        if (rec.history_of_present_illness) sections.push({ title: "History of Present Illness", body: rec.history_of_present_illness });
        if (rec.medications)
          sections.push({
            title: "Medications",
            body: Array.isArray(rec.medications)
              ? rec.medications.map((m) => (typeof m === "string" ? m : m.name)).join("\n")
              : String(rec.medications),
          });
        if (rec.allergies)
          sections.push({
            title: "Allergies",
            body: Array.isArray(rec.allergies)
              ? rec.allergies.map((a) => (typeof a === "string" ? a : a.substance)).join("\n")
              : String(rec.allergies),
          });
        if (rec.assessment) sections.push({ title: "Assessment", body: rec.assessment });
        if (rec.plan) sections.push({ title: "Plan", body: rec.plan });
        newDocs["Medical Record"] = {
          generated: `Today, ${now}`,
          badge: "Pipeline-generated",
          sections: sections.length > 0 ? sections : [{ title: "Raw Record", body: JSON.stringify(rec, null, 2) }],
        };
      }

      try {
        if (result.structured_record) {
          const html = await generateRecord(result.structured_record, "discharge", "html", clinicalData);
          newDocs["Discharge Note"] = {
            generated: `Today, ${now}`,
            badge: "Auto-generated",
            sections: [{ title: "Discharge Note", html }],
          };
        }
      } catch (e) {
        console.warn("Discharge note generation failed:", e);
      }

      newDocs["Uploaded Docs"] = documents["Uploaded Docs"];
      setDocuments(newDocs);

      const clinicalAlerts = [];
      if (clinicalData) {
        if (clinicalData.risk_level) {
          clinicalAlerts.push({
            level: clinicalData.risk_level,
            text: `Overall risk level: ${clinicalData.risk_level.toUpperCase()}`,
          });
        }
        if (clinicalData.allergy_alerts && Array.isArray(clinicalData.allergy_alerts)) {
          clinicalData.allergy_alerts.forEach((a) => {
            clinicalAlerts.push({
              level: "high",
              text: typeof a === "string" ? a : a.message || a.description || JSON.stringify(a),
            });
          });
        }
        if (clinicalData.drug_interactions && Array.isArray(clinicalData.drug_interactions)) {
          clinicalData.drug_interactions.forEach((d) => {
            clinicalAlerts.push({
              level: "moderate",
              text: typeof d === "string" ? d : d.message || d.description || JSON.stringify(d),
            });
          });
        }
      }

      const segCount = segmentsRef.current.length;
      const duration = timer.display;
      const summaryId = nextIdRef.current++;
      const summaryMsg = {
        id: summaryId,
        speaker: AGENT,
        time: now,
        text: result.clinical_note
          ? result.clinical_note.slice(0, 200) + (result.clinical_note.length > 200 ? "…" : "")
          : "Session has been processed. Your clinical documents are ready for review.",
        summaryHtml: soapHtml || null,
        cardType: "summary",
        clinicalAlerts,
        stats: [
          { value: segCount, label: "Utterances" },
          { value: duration, label: "Duration" },
          {
            value: result.structured_record
              ? Object.keys(result.structured_record).filter((k) => result.structured_record[k]).length
              : 0,
            label: "Fields",
          },
          ...(clinicalData?.risk_level
            ? [{ value: clinicalData.risk_level.toUpperCase(), label: "Risk" }]
            : []),
        ],
        pipeline: [],
      };
      setMsgs((prev) => [...prev, summaryMsg]);
      setTimeout(() => setVis((prev) => new Set([...prev, summaryId])), 100);

      setTimeout(() => {
        const reviewId = nextIdRef.current++;
        const mergedValidation = {
          ...(result.validation_report || {}),
          warnings: [
            ...((result.validation_report || {}).warnings || []),
            ...(clinicalData?.allergy_alerts || []).map((a) => ({
              field: "allergies",
              message: typeof a === "string" ? a : a.message,
            })),
          ],
          contradictions: [
            ...((result.validation_report || {}).contradictions || (result.validation_report || {}).conflicts || []),
            ...(clinicalData?.drug_interactions || []).map((d) => ({
              field: "medications",
              message: typeof d === "string" ? d : d.message,
            })),
          ],
        };
        const fields = result.structured_record
          ? buildReviewFields(result.structured_record, mergedValidation)
          : [];
        const reviewMsg = {
          id: reviewId,
          speaker: AGENT,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          text: "",
          cardType: "review",
          fields,
          approved: false,
          pipeline: [],
        };
        setMsgs((prev) => [...prev, reviewMsg]);
        setTimeout(() => setVis((prev) => new Set([...prev, reviewId])), 100);
      }, 1200);

      notify("Pipeline complete — please review changes", "success");
    } catch (err) {
      notify(`Pipeline failed: ${err.message}`, "error");
    } finally {
      setPipelineRunning(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, notify, timer, documents, buildReviewFields]);

  /* ── Approve record changes ── */
  const handleApproveChanges = useCallback(
    (msgId) => {
      setMsgs((prev) => prev.map((m) => (m.id === msgId ? { ...m, approved: true } : m)));
      notify("Changes approved — patient record updated", "success");
    },
    [notify]
  );

  /* ── End Session ── */
  const handleEndSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      await endSession(sessionId);
      setSessionActive(false);
      setRecording(false);
      setTranscribing(false);
      timer.stop();
      notify("Session ended", "success");
    } catch (err) {
      notify(`Failed to end session: ${err.message}`, "error");
    }
  }, [sessionId, notify, timer]);

  /* ── Export handler ── */
  const handleExport = useCallback(
    async (docTab) => {
      if (!pipelineResult?.structured_record) {
        notify("No data to export yet", "error");
        return;
      }
      try {
        const templateMap = {
          "Session Summary": "soap",
          "Discharge Note": "discharge",
          "Medical Record": "soap",
        };
        const template = templateMap[docTab] || "soap";
        const blob = await generateRecord(
          pipelineResult.structured_record,
          template,
          "pdf",
          pipelineResult.clinical_suggestions
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${docTab.replace(/\s/g, "_")}_${new Date().toISOString().slice(0, 10)}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        notify("PDF downloaded", "success");
      } catch (err) {
        notify(`Export failed: ${err.message}`, "error");
      }
    },
    [pipelineResult, notify]
  );

  /* ── Upload handler (passed to UploadPanel) ── */
  const handleUpload = useCallback(async () => {
    if (!sessionId) {
      notify("Start a session before uploading", "error");
      return;
    }
    setUploadOpen(false);
    const toUpload = [...uploadedFiles];
    notify(`Uploading ${toUpload.length} file(s) — running OCR…`, "success");
    try {
      const res = await uploadDocuments(sessionId, toUpload);
      const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      for (const file of res.files || []) {
        if (file.error) {
          notify(`OCR failed for ${file.original_name}: ${file.error}`, "error");
          continue;
        }
        const docMsgId = nextIdRef.current++;
        const docMsg = {
          id: docMsgId,
          speaker: AGENT,
          time: now,
          text: file.agent_summary || "Document processed successfully.",
          cardType: "document",
          docType: file.document_type?.replace(/_/g, " ") || "document",
          fieldChanges: file.field_changes || [],
          conflictDetails: file.conflict_details || [],
          stats: [
            { value: file.fields_extracted || 0, label: "Fields" },
            { value: `${Math.round((file.overall_confidence || 0) * 100)}%`, label: "Confidence" },
            { value: file.conflicts_detected || 0, label: "Conflicts" },
          ],
          pipeline: [],
        };
        setMsgs((prev) => [...prev, docMsg]);
        setTimeout(() => setVis((prev) => new Set([...prev, docMsgId])), 100);
      }
      setUploadedFiles([]);
      notify(`${res.uploaded} document(s) analyzed successfully`, "success");
    } catch (err) {
      notify(`Upload failed: ${err.message}`, "error");
    }
  }, [sessionId, uploadedFiles, notify]);

  /* ── Voice / VAD ── */
  const speech = useVoiceCapture({
    enabled: recording && sessionActive,
    muted,
    onUtterance: useCallback((text) => addUtterance(text), [addUtterance]),
    onError: useCallback((msg) => notify(msg, "error"), [notify]),
    silenceMs: 2500,
  });

  const waveActive = recording && !muted && (speech.userSpeaking || speech.listening);

  const handleToggleRecording = useCallback(() => {
    if (recording) speech.flush();
    setRecording((r) => !r);
  }, [recording, speech]);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&family=Lora:wght@400;500&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        html,body{height:100%}
        ::-webkit-scrollbar{display:none}

        @keyframes blink{0%,100%{opacity:1}50%{opacity:0.15}}
        @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes orb1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(40px,-30px) scale(1.08)}}
        @keyframes orb2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-30px,40px) scale(1.06)}}
        @keyframes orb3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(20px,30px) scale(1.05)}}

        .blink{animation:blink 1.6s ease infinite}
        .fadeUp{animation:fadeUp 0.28s ease forwards}
        .ib:hover{background:rgba(255,255,255,0.08)!important}
        .pc:hover{background:rgba(255,255,255,0.06)!important}
        .orb1{animation:orb1 12s ease-in-out infinite}
        .orb2{animation:orb2 16s ease-in-out infinite}
        .orb3{animation:orb3 20s ease-in-out infinite}
        input::placeholder,textarea::placeholder{color:rgba(255,255,255,0.2)}
        input:focus,textarea:focus{border-color:rgba(255,255,255,0.16)!important;outline:none}
      `}</style>

      {toast && (
        <Toast key={toast.key} message={toast.message} type={toast.type} onClose={clearToast} />
      )}

      <div
        style={{
          height: "100vh",
          minHeight: "100vh",
          background: "#0e0f11",
          fontFamily: "'DM Sans', sans-serif",
          color: "rgba(255,255,255,0.88)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Background Orbs */}
        <div style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0, overflow: "hidden" }}>
          <div
            className="orb1"
            style={{
              position: "absolute", top: "-10%", right: "5%", width: 420, height: 420,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(200,210,220,0.18) 0%, rgba(160,175,190,0.08) 50%, transparent 75%)",
              filter: "blur(32px)",
            }}
          />
          <div
            className="orb2"
            style={{
              position: "absolute", bottom: "-5%", left: "38%", width: 500, height: 320,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(210,215,225,0.14) 0%, rgba(180,190,200,0.06) 50%, transparent 75%)",
              filter: "blur(40px)",
            }}
          />
          <div
            className="orb3"
            style={{
              position: "absolute", top: "35%", left: "-8%", width: 360, height: 360,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(190,200,215,0.12) 0%, transparent 70%)",
              filter: "blur(30px)",
            }}
          />
        </div>

        <AppHeader
          sessionActive={sessionActive}
          sessionId={sessionId}
          tab={tab}
          onStartSession={handleStartSession}
          onEndSession={handleEndSession}
          onTabChange={setTab}
        />

        <div style={{ display: "flex", flex: 1, overflow: "hidden", position: "relative", zIndex: 1 }}>
          <Sidebar
            sessionActive={sessionActive}
            pipelineStep={pipelineStep}
            transcribing={transcribing}
            timer={timer}
          />

          {tab === "Transcription" ? (
            <TranscriptionFeed
              feedRef={feedRef}
              sessionActive={sessionActive}
              msgs={msgs}
              vis={vis}
              transcribing={transcribing}
              pipelineRunning={pipelineRunning}
              pipelineStep={pipelineStep}
              onApprove={handleApproveChanges}
              onSwitchTab={setTab}
            />
          ) : (
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <PatientInfoPanel
                documents={documents}
                uploadedFiles={uploadedFiles}
                onExport={handleExport}
              />
            </div>
          )}
        </div>

        {uploadOpen && (
          <UploadPanel
            onClose={() => setUploadOpen(false)}
            uploadedFiles={uploadedFiles}
            setUploadedFiles={setUploadedFiles}
            onUpload={handleUpload}
            fileInputRef={fileInputRef}
          />
        )}

        <Footer
          waveActive={waveActive}
          transcribing={transcribing}
          pipelineRunning={pipelineRunning}
          pipelineStep={pipelineStep}
          speech={speech}
          sessionActive={sessionActive}
          recording={recording}
          muted={muted}
          demoText={demoText}
          setDemoText={setDemoText}
          uploadOpen={uploadOpen}
          onToggleRecording={handleToggleRecording}
          onToggleMuted={() => setMuted((m) => !m)}
          onCompleteTranscription={handleCompleteTranscription}
          onToggleUpload={() => setUploadOpen((n) => !n)}
          onSendUtterance={addUtterance}
        />
      </div>
    </>
  );
}
