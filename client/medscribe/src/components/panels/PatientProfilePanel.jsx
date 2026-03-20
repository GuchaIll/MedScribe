import { useMemo } from "react";

/*  Helpers  */
function formatDate(d) {
  if (!d) return null;
  try {
    return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  } catch { return d; }
}

function calcAge(dob) {
  if (!dob) return null;
  try {
    const b = new Date(dob);
    const now = new Date();
    let age = now.getFullYear() - b.getFullYear();
    const m = now.getMonth() - b.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < b.getDate())) age--;
    return age;
  } catch { return null; }
}

function val(v) {
  if (v == null || v === "" || v === "None") return null;
  return v;
}

/*  Sub-components  */

function SecHead({ title, color = "#667eea" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 10, borderLeft: "3px solid " + color, marginBottom: 10 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "#666", fontFamily: "'DM Mono', monospace" }}>{title}</span>
    </div>
  );
}

function FR({ label, value, mono = false, color }) {
  const display = value ?? "\u2014";
  const isEmpty = value == null;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "42% 58%", alignItems: "baseline", padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>
      <span style={{ fontSize: 11, color: "#888", fontFamily: "'DM Mono', monospace", paddingRight: 8, lineHeight: 1.5 }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: isEmpty ? 400 : 500, color: color || (isEmpty ? "#bbb" : "#1a1a1a"), fontFamily: mono ? "'DM Mono', monospace" : "'DM Sans', sans-serif", lineHeight: 1.5, wordBreak: "break-word" }}>{String(display)}</span>
    </div>
  );
}

function Card({ children, style }) {
  return (
    <div style={{ background: "#fff", border: "1px solid rgba(0,0,0,0.07)", borderRadius: 12, padding: "14px 16px", ...style }}>
      {children}
    </div>
  );
}

function Pill({ label, color = "#667eea", bg = "rgba(102,126,234,0.1)" }) {
  return (
    <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 99, background: bg, color, fontFamily: "'DM Mono', monospace", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
  );
}

function AllergyPill({ allergy }) {
  const text = typeof allergy === "string" ? allergy : allergy?.allergen || allergy?.substance || allergy?.name || "Unknown";
  const sev = typeof allergy === "object" ? allergy?.severity : null;
  const reaction = typeof allergy === "object" ? allergy?.reaction : null;
  const isHigh = sev === "severe" || sev === "high";
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 10px", borderRadius: 8, background: isHigh ? "rgba(239,68,68,0.07)" : "rgba(234,179,8,0.07)", border: "1px solid " + (isHigh ? "rgba(239,68,68,0.25)" : "rgba(234,179,8,0.25)"), marginBottom: 5 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: isHigh ? "#dc2626" : "#a16207" }}>{text}</span>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {sev && <Pill label={sev} color={isHigh ? "#dc2626" : "#a16207"} bg={isHigh ? "rgba(239,68,68,0.1)" : "rgba(234,179,8,0.1)"} />}
        {reaction && <span style={{ fontSize: 10, color: "#888" }}>{reaction}</span>}
      </div>
    </div>
  );
}

function MedRow({ med }) {
  const name = typeof med === "string" ? med : med?.name || med?.medication || "Unknown";
  const dose = typeof med === "object" ? med?.dose || med?.dosage : null;
  const freq = typeof med === "object" ? med?.frequency : null;
  const route = typeof med === "object" ? med?.route : null;
  const status = typeof med === "object" ? med?.status || "Active" : "Active";
  const isActive = !status || status === "Active";
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a1a" }}>{name}</div>
        {(dose || freq || route) && (
          <div style={{ fontSize: 10, color: "#888", fontFamily: "'DM Mono', monospace", marginTop: 1 }}>{[dose, freq, route].filter(Boolean).join(" \u00b7 ")}</div>
        )}
      </div>
      <Pill label={status} color={isActive ? "#16a34a" : "#666"} bg={isActive ? "rgba(34,197,94,0.1)" : "rgba(156,163,175,0.15)"} />
    </div>
  );
}

function LabRow({ lab }) {
  const name = typeof lab === "string" ? lab : lab?.test || lab?.name || "Unknown";
  const value = typeof lab === "object" ? (lab?.value ?? lab?.result) : null;
  const unit = typeof lab === "object" ? lab?.unit : null;
  const ref = typeof lab === "object" ? lab?.reference || lab?.reference_range : null;
  const date = typeof lab === "object" ? lab?.date : null;
  let abnormal = typeof lab === "object" && (lab?.status === "abnormal" || lab?.abnormal === true);
  if (!abnormal && value != null && ref) {
    const num = parseFloat(String(value));
    const ltM = String(ref).match(/^<\s*([\d.]+)$/);
    const gtM = String(ref).match(/^>\s*([\d.]+)$/);
    if (!isNaN(num)) {
      if (ltM && num >= parseFloat(ltM[1])) abnormal = true;
      if (gtM && num <= parseFloat(gtM[1])) abnormal = true;
    }
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "30% 22% 18% 18% 12%", alignItems: "center", padding: "5px 8px", borderRadius: 6, background: abnormal ? "rgba(239,68,68,0.04)" : "transparent", borderBottom: "1px solid rgba(0,0,0,0.05)", fontSize: 11 }}>
      <span style={{ fontWeight: 600, color: "#1a1a1a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
      <span style={{ fontWeight: 700, color: abnormal ? "#dc2626" : "#1a1a1a", fontFamily: "'DM Mono', monospace" }}>{value ?? "\u2014"}{abnormal ? " !" : ""}</span>
      <span style={{ color: "#888", fontFamily: "'DM Mono', monospace" }}>{unit || "\u2014"}</span>
      <span style={{ color: "#aaa", fontFamily: "'DM Mono', monospace" }}>{ref || "\u2014"}</span>
      <span style={{ color: "#bbb", fontFamily: "'DM Mono', monospace", fontSize: 10 }}>{formatDate(date) || "\u2014"}</span>
    </div>
  );
}

function CompactGrid({ items }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "2px 16px" }}>
      {items.map(([label, v]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>
          <span style={{ fontSize: 11, color: "#888", fontFamily: "'DM Mono', monospace", flexShrink: 0, paddingRight: 8 }}>{label}</span>
          <span style={{ fontSize: 11, color: v ? "#1a1a1a" : "#ccc", fontWeight: v ? 500 : 400, fontFamily: "'DM Sans', sans-serif", maxWidth: "55%", textAlign: "right", wordBreak: "break-word" }}>{v || "\u2014"}</span>
        </div>
      ))}
    </div>
  );
}

function HPIItem({ item }) {
  const symptom = typeof item === "string" ? item : item?.symptom;
  const onset = typeof item === "object" ? item?.onset : null;
  const progression = typeof item === "object" ? item?.progression : null;
  const triggers = typeof item === "object" ? item?.triggers : null;
  const relieving = typeof item === "object" ? item?.relieving_factors || item?.relieving : null;
  const assoc = typeof item === "object" ? item?.associated_symptoms || item?.associated_sx : null;
  return (
    <div style={{ padding: "8px 12px", borderRadius: 8, background: "#f9fafb", border: "1px solid rgba(0,0,0,0.06)", marginBottom: 6 }}>
      {symptom && <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a1a", marginBottom: 4 }}>{symptom}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        {onset && <FR label="Onset" value={onset} />}
        {progression && <FR label="Progression" value={progression} />}
        {triggers && <FR label="Triggers" value={triggers} />}
        {relieving && <FR label="Relieving" value={relieving} />}
        {assoc && <FR label="Assoc. Sx" value={assoc} />}
      </div>
    </div>
  );
}

function PMHList({ items, label, keyField = "name" }) {
  if (!items?.length) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>{label}</div>
      {items.map((item, i) => {
        const name = typeof item === "string" ? item : item?.[keyField] || item?.name || JSON.stringify(item);
        const extra = typeof item === "object" ? [item?.status, item?.onset_year, item?.year, item?.reason].filter(Boolean).join(" \u00b7 ") : null;
        return (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 8px", borderRadius: 6, background: i % 2 === 0 ? "#f9fafb" : "transparent", marginBottom: 2 }}>
            <span style={{ fontSize: 12, color: "#1a1a1a" }}>{name}</span>
            {extra && <span style={{ fontSize: 10, color: "#888", fontFamily: "'DM Mono', monospace" }}>{extra}</span>}
          </div>
        );
      })}
    </div>
  );
}

/*  Main Component  */
function PatientProfilePanel({ structuredRecord, sessionActive, lastUpdated }) {
  const r = structuredRecord || {};

  const dem = r.demographics || {};
  const vitals = r.vitals || {};
  const allergies = r.allergies || [];
  const medications = r.medications || [];
  const pmh = r.past_medical_history || {};
  const familyHx = r.family_history || [];
  const socialHx = r.social_history || {};
  const ros = r.review_of_systems || {};
  const physExam = r.physical_exam || {};
  const labs = r.labs || [];
  const procedures = r.procedures || [];
  const problemList = r.problem_list || [];
  const riskFactors = r.risk_factors || [];
  const chiefComplaint = r.chief_complaint || {};
  const hpi = r.hpi || [];
  const assessment = r.assessment || {};
  const plan = r.plan || {};
  const visit = r.visit || {};
  const diagnoses = r.diagnoses || [];

  const age = useMemo(() => calcAge(dem.date_of_birth), [dem.date_of_birth]);
  const contactInfo = dem.contact_info || {};
  const insurance = dem.insurance || {};
  const emergencyContact = dem.emergency_contact || {};
  const patientName = dem.full_name || dem.name || "Patient";
  const initials = patientName.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  if (!structuredRecord) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", padding: 40, textAlign: "center", background: "#fafafa" }}>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: "#f0f0f0", marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ fontSize: 20, color: "#bbb", fontFamily: "'DM Sans', sans-serif", fontWeight: 700 }}>Rx</span>
        </div>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: "#666", marginBottom: 8, fontFamily: "'DM Sans', sans-serif" }}>No Medical Record Available</h3>
        <p style={{ fontSize: 12, color: "#aaa", fontFamily: "'DM Mono', monospace", maxWidth: 280, lineHeight: 1.6 }}>
          Start a transcription session or upload patient documents to populate the medical record.
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#f5f6f8", padding: "20px 24px", fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`@keyframes pulse2{0%,100%{opacity:1}50%{opacity:0.45}}`}</style>

      {/* Live bar */}
      {sessionActive && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 8, marginBottom: 16, background: "rgba(34,197,94,0.07)", border: "1px solid rgba(34,197,94,0.2)" }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#22c55e", animation: "pulse2 1.8s infinite" }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: "#16a34a", fontFamily: "'DM Mono', monospace" }}>Live \u2014 record updating in real-time</span>
          {lastUpdated && <span style={{ fontSize: 10, color: "#22c55e", marginLeft: "auto", fontFamily: "'DM Mono', monospace" }}>{new Date(lastUpdated).toLocaleTimeString()}</span>}
        </div>
      )}

      {/* Patient header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18, padding: "14px 18px", borderRadius: 14, background: "#fff", border: "1px solid rgba(0,0,0,0.07)" }}>
        <div style={{ width: 54, height: 54, borderRadius: 12, flexShrink: 0, background: "linear-gradient(135deg,#667eea 0%,#764ba2 100%)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 18, fontWeight: 700 }}>{initials}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#1a1a1a", marginBottom: 4 }}>{patientName}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {age && <Pill label={age + " yrs"} />}
            {dem.sex && <Pill label={dem.sex} color="#4b5563" bg="rgba(75,85,99,0.1)" />}
            {dem.gender && dem.gender !== dem.sex && <Pill label={dem.gender} color="#4b5563" bg="rgba(75,85,99,0.08)" />}
            {dem.mrn && <Pill label={"MRN " + dem.mrn} color="#6b7280" bg="rgba(107,114,128,0.08)" />}
            {visit.date && <Pill label={"Visit: " + formatDate(visit.date)} color="#6b7280" bg="rgba(107,114,128,0.08)" />}
            {visit.provider && <Pill label={visit.provider} color="#6b7280" bg="rgba(107,114,128,0.08)" />}
          </div>
        </div>
        {allergies.length > 0 && (
          <div style={{ padding: "6px 12px", borderRadius: 8, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", flexShrink: 0 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#dc2626", fontFamily: "'DM Mono', monospace" }}>ALLERGY ALERT \u2014 {allergies.length}</span>
          </div>
        )}
      </div>

      {/* Row 1: Demographics / Vitals+CC / Allergies+Meds */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr 1fr", gap: 14, marginBottom: 14 }}>

        {/* A: Demographics */}
        <Card>
          <SecHead title="Demographics" color="#667eea" />
          <FR label="Full Name" value={val(dem.full_name || dem.name)} />
          <FR label="Date of Birth" value={formatDate(dem.date_of_birth)} mono />
          <FR label="Age" value={age ? age + " years" : null} mono />
          <FR label="Gender" value={val(dem.gender)} />
          <FR label="Biological Sex" value={val(dem.sex)} />
          <FR label="MRN" value={val(dem.mrn)} mono />

          <div style={{ marginTop: 12 }}>
            <SecHead title="Anthropometrics" color="#a78bfa" />
            <FR label="Height" value={val(vitals.height || dem.height)} mono />
            <FR label="Weight" value={val(vitals.weight || dem.weight)} mono />
            <FR label="BMI" value={val(vitals.bmi || dem.bmi)} mono />
          </div>

          {(contactInfo.phone || contactInfo.email || contactInfo.address || insurance.provider) && (
            <div style={{ marginTop: 12 }}>
              <SecHead title="Contact & Insurance" color="#34d399" />
              <FR label="Phone" value={val(contactInfo.phone)} mono />
              <FR label="Email" value={val(contactInfo.email)} />
              <FR label="Address" value={val([contactInfo.address, contactInfo.city, contactInfo.state, contactInfo.zip].filter(Boolean).join(", ") || null)} />
              <FR label="Insurance" value={val(insurance.provider)} />
              <FR label="Policy No." value={val(insurance.policy_number)} mono />
            </div>
          )}

          {(emergencyContact.name || emergencyContact.phone) && (
            <div style={{ marginTop: 12 }}>
              <SecHead title="Emergency Contact" color="#f97316" />
              <FR label="Name" value={val(emergencyContact.name)} />
              <FR label="Relationship" value={val(emergencyContact.relationship)} />
              <FR label="Phone" value={val(emergencyContact.phone)} mono />
            </div>
          )}
        </Card>

        {/* B: Vitals + Chief Complaint + HPI */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Card>
            <SecHead title="Vitals" color="#ef4444" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 20px" }}>
              <FR label="Blood Pressure" value={val(vitals.blood_pressure)} mono />
              <FR label="Heart Rate" value={vitals.heart_rate ? vitals.heart_rate + " bpm" : null} mono />
              <FR label="Respiratory Rate" value={vitals.respiratory_rate ? vitals.respiratory_rate + "/min" : null} mono />
              <FR label="Temperature" value={vitals.temperature ? vitals.temperature + " \u00b0F" : null} mono />
              <FR label="O\u2082 Saturation" value={vitals.spo2 ? vitals.spo2 + "%" : null} mono />
              <FR label="Timestamp" value={formatDate(vitals.timestamp)} mono />
            </div>
          </Card>

          <Card>
            <SecHead title="Chief Complaint" color="#3b82f6" />
            {(() => {
              const cc = chiefComplaint;
              const hasData = cc && (cc.free_text || cc.onset || cc.duration || cc.severity || cc.location);
              if (!hasData) return <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>;
              return (
                <>
                  {cc.free_text && <div style={{ fontSize: 13, fontWeight: 500, color: "#1a1a1a", marginBottom: 8, lineHeight: 1.5 }}>{cc.free_text}</div>}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
                    <FR label="Onset" value={val(cc.onset)} />
                    <FR label="Duration" value={val(cc.duration)} />
                    <FR label="Severity" value={val(cc.severity)} />
                    <FR label="Location" value={val(cc.location)} />
                  </div>
                </>
              );
            })()}
          </Card>

          {hpi.length > 0 && (
            <Card>
              <SecHead title="History of Present Illness" color="#3b82f6" />
              {hpi.map((item, i) => <HPIItem key={i} item={item} />)}
            </Card>
          )}
        </div>

        {/* C: Allergies + Medications */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Card style={{ border: allergies.length > 0 ? "1px solid rgba(239,68,68,0.3)" : "1px solid rgba(0,0,0,0.07)", background: allergies.length > 0 ? "rgba(239,68,68,0.02)" : "#fff" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <SecHead title="Allergies" color="#ef4444" />
              {allergies.length > 0 && <Pill label={allergies.length + " documented"} color="#dc2626" bg="rgba(239,68,68,0.1)" />}
            </div>
            {allergies.length === 0
              ? <span style={{ fontSize: 12, color: "#bbb" }}>No allergies documented</span>
              : allergies.map((a, i) => <AllergyPill key={i} allergy={a} />)}
          </Card>

          <Card style={{ flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <SecHead title="Medications" color="#8b5cf6" />
              {medications.length > 0 && <Pill label={String(medications.length)} color="#8b5cf6" bg="rgba(139,92,246,0.1)" />}
            </div>
            {medications.length === 0
              ? <span style={{ fontSize: 12, color: "#bbb" }}>No medications documented</span>
              : medications.map((med, i) => <MedRow key={i} med={med} />)}
          </Card>
        </div>
      </div>

      {/* Row 2: Past Medical History + Family History + Social History */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        <Card>
          <SecHead title="Past Medical History" color="#f59e0b" />
          <PMHList items={pmh.chronic_conditions} label="Chronic Conditions" keyField="name" />
          <PMHList items={pmh.surgeries} label="Surgeries" keyField="name" />
          <PMHList items={pmh.hospitalizations} label="Hospitalizations" keyField="reason" />
          <PMHList items={pmh.prior_diagnoses} label="Prior Diagnoses" keyField="name" />
          {!pmh.chronic_conditions?.length && !pmh.surgeries?.length && !pmh.hospitalizations?.length && !pmh.prior_diagnoses?.length && (
            <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>
          )}
        </Card>

        <Card>
          <SecHead title="Family History" color="#10b981" />
          {familyHx.length === 0 ? (
            <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>
          ) : familyHx.map((item, i) => {
            const member = typeof item === "string" ? null : item?.member || item?.relation;
            const conds = typeof item === "string" ? item : Array.isArray(item?.conditions) ? item.conditions.join(", ") : item?.conditions || "";
            return (
              <div key={i} style={{ marginBottom: 6, padding: "6px 10px", borderRadius: 8, background: "#f9fafb", border: "1px solid rgba(0,0,0,0.05)" }}>
                {member && <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 3 }}>{member}</div>}
                <div style={{ fontSize: 12, color: "#1a1a1a" }}>{conds || "\u2014"}</div>
              </div>
            );
          })}
        </Card>

        <Card>
          <SecHead title="Social History" color="#06b6d4" />
          <FR label="Tobacco" value={val(socialHx.tobacco)} />
          <FR label="Alcohol" value={val(socialHx.alcohol)} />
          <FR label="Drug Use" value={val(socialHx.drug_use)} />
          <FR label="Occupation" value={val(socialHx.occupation)} />
          <FR label="Exercise" value={val(socialHx.exercise)} />
          <FR label="Diet" value={val(socialHx.diet)} />
          <FR label="Sexual Activity" value={val(socialHx.sexual_activity)} />
        </Card>
      </div>

      {/* Row 3: Review of Systems */}
      <Card style={{ marginBottom: 14 }}>
        <SecHead title="Review of Systems" color="#6366f1" />
        <CompactGrid items={[
          ["Cardiovascular", val(ros.cardiovascular)],
          ["Respiratory", val(ros.respiratory)],
          ["Neurological", val(ros.neurological)],
          ["Gastrointestinal", val(ros.gastrointestinal)],
          ["Musculoskeletal", val(ros.musculoskeletal)],
          ["Dermatological", val(ros.dermatological)],
          ["Psychiatric", val(ros.psychiatric)],
          ["Endocrine", val(ros.endocrine)],
          ["Genitourinary", val(ros.genitourinary)],
          ["Hematologic", val(ros.hematologic)],
        ]} />
      </Card>

      {/* Row 4: Physical Exam + Lab Results */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <Card>
          <SecHead title="Physical Exam" color="#0ea5e9" />
          <CompactGrid items={[
            ["General", val(physExam.general)],
            ["Cardiovascular", val(physExam.cardiovascular)],
            ["Respiratory", val(physExam.respiratory)],
            ["Neurological", val(physExam.neurological)],
            ["Abdomen", val(physExam.abdomen)],
            ["Musculoskeletal", val(physExam.musculoskeletal)],
            ["Skin", val(physExam.skin)],
            ["Head / Neck", val(physExam.head_neck)],
          ]} />
        </Card>

        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <SecHead title="Laboratory Results" color="#ec4899" />
            {labs.length > 0 && <Pill label={labs.length + " tests"} color="#ec4899" bg="rgba(236,72,153,0.1)" />}
          </div>
          {labs.length === 0 ? (
            <span style={{ fontSize: 12, color: "#bbb" }}>No lab results documented</span>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "30% 22% 18% 18% 12%", padding: "4px 8px", marginBottom: 2 }}>
                {["Test", "Value", "Unit", "Reference", "Date"].map((h) => (
                  <span key={h} style={{ fontSize: 9, fontWeight: 700, color: "#aaa", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", letterSpacing: "0.06em" }}>{h}</span>
                ))}
              </div>
              {labs.map((lab, i) => <LabRow key={i} lab={lab} />)}
            </>
          )}
        </Card>
      </div>

      {/* Row 5: Diagnoses + Problem List + Risk Factors */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        <Card>
          <SecHead title="Diagnoses" color="#f43f5e" />
          {diagnoses.length === 0 ? (
            <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>
          ) : diagnoses.map((dx, i) => {
            const name = typeof dx === "string" ? dx : dx?.name || dx?.diagnosis || JSON.stringify(dx);
            const status = typeof dx === "object" ? dx?.status : null;
            return (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0", borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
                <span style={{ fontSize: 12, color: "#1a1a1a" }}>{name}</span>
                {status && <Pill label={status} color="#f43f5e" bg="rgba(244,63,94,0.08)" />}
              </div>
            );
          })}
        </Card>

        <Card>
          <SecHead title="Problem List" color="#f43f5e" />
          {problemList.length === 0 ? (
            <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>
          ) : problemList.map((p, i) => {
            const name = typeof p === "string" ? p : p?.name || p?.problem || JSON.stringify(p);
            return <div key={i} style={{ fontSize: 12, color: "#1a1a1a", padding: "4px 6px", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>{name}</div>;
          })}
        </Card>

        <Card>
          <SecHead title="Risk Factors" color="#fb923c" />
          {riskFactors.length === 0 ? (
            <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>
          ) : riskFactors.map((rf, i) => {
            const name = typeof rf === "string" ? rf : rf?.name || rf?.factor || JSON.stringify(rf);
            return <div key={i} style={{ fontSize: 12, color: "#1a1a1a", padding: "4px 6px", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>{name}</div>;
          })}
        </Card>
      </div>

      {/* Row 6: Assessment + Plan */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <Card>
          <SecHead title="Assessment" color="#8b5cf6" />
          {(() => {
            const hasAny = assessment?.likely_diagnoses?.length || assessment?.differential_diagnoses?.length || assessment?.clinical_reasoning;
            if (!hasAny) return <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>;
            return (
              <>
                {assessment.clinical_reasoning && (
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>Clinical Reasoning</div>
                    <div style={{ fontSize: 12, color: "#1a1a1a", lineHeight: 1.6 }}>{assessment.clinical_reasoning}</div>
                  </div>
                )}
                {assessment.likely_diagnoses?.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>Likely Diagnoses</div>
                    {assessment.likely_diagnoses.map((d, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#1a1a1a", padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>{typeof d === "string" ? d : d?.name || JSON.stringify(d)}</div>
                    ))}
                  </div>
                )}
                {assessment.differential_diagnoses?.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>Differential Diagnoses</div>
                    {assessment.differential_diagnoses.map((d, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#444", padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>{typeof d === "string" ? d : d?.name || JSON.stringify(d)}</div>
                    ))}
                  </div>
                )}
              </>
            );
          })()}
        </Card>

        <Card>
          <SecHead title="Plan" color="#10b981" />
          {(() => {
            const hasAny = plan.medications_prescribed?.length || plan.tests_ordered?.length || plan.lifestyle_recommendations?.length || plan.follow_up || plan.referrals?.length;
            if (!hasAny) return <span style={{ fontSize: 12, color: "#bbb" }}>Not documented</span>;
            const PlanSec = ({ label, items }) => {
              if (!items?.length) return null;
              return (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>{label}</div>
                  {items.map((item, i) => {
                    const text = typeof item === "string" ? item : item?.name || item?.medication || item?.test || JSON.stringify(item);
                    return <div key={i} style={{ fontSize: 12, color: "#1a1a1a", padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,0.04)" }}>{text}</div>;
                  })}
                </div>
              );
            };
            return (
              <>
                <PlanSec label="Medications Prescribed" items={plan.medications_prescribed} />
                <PlanSec label="Tests Ordered" items={plan.tests_ordered} />
                <PlanSec label="Lifestyle Recommendations" items={plan.lifestyle_recommendations} />
                <PlanSec label="Referrals" items={plan.referrals} />
                {plan.follow_up && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#888", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>Follow-Up</div>
                    <div style={{ fontSize: 12, color: "#1a1a1a", padding: "8px 12px", borderRadius: 8, background: "rgba(16,185,129,0.05)", border: "1px solid rgba(16,185,129,0.15)" }}>{plan.follow_up}</div>
                  </div>
                )}
              </>
            );
          })()}
        </Card>
      </div>

      {/* Procedures (if any) */}
      {procedures.length > 0 && (
        <Card style={{ marginBottom: 14 }}>
          <SecHead title="Procedures" color="#64748b" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
            {procedures.map((p, i) => {
              const name = typeof p === "string" ? p : p?.name || p?.procedure || JSON.stringify(p);
              const date = typeof p === "object" ? p?.date : null;
              return (
                <div key={i} style={{ padding: "7px 10px", borderRadius: 8, background: "#f9fafb", border: "1px solid rgba(0,0,0,0.06)" }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "#1a1a1a" }}>{name}</div>
                  {date && <div style={{ fontSize: 10, color: "#888", fontFamily: "'DM Mono', monospace", marginTop: 2 }}>{formatDate(date)}</div>}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", padding: "10px 16px", borderRadius: 8, background: "#fff", border: "1px solid rgba(0,0,0,0.06)", marginTop: 4 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#aaa", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", letterSpacing: "0.08em" }}>Legend</span>
        {[
          { color: "#22c55e", bg: "rgba(34,197,94,0.1)", label: "Extracted / modified field" },
          { color: "#f59e0b", bg: "rgba(245,158,11,0.1)", label: "Uncertain (< 70% confidence)" },
          { color: "#ef4444", bg: "rgba(239,68,68,0.1)", label: "Conflict \u2014 DB vs extracted" },
          { color: "#dc2626", bg: "rgba(220,38,38,0.08)", label: "Abnormal lab value" },
        ].map(({ color, bg, label }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: 3, background: bg, border: "1.5px solid " + color }} />
            <span style={{ fontSize: 10, color: "#888", fontFamily: "'DM Sans', sans-serif" }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default PatientProfilePanel;
