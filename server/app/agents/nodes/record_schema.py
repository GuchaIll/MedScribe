"""
Full hierarchical clinical record schema.

Single-value fields (name, dob, sex, mrn, contact_info, insurance):
  DB values take precedence — extraction only fills when empty.

List/appendable fields (chronic_conditions, medications, allergies,
  problem_list, hpi, family_history, etc.):
  DB baseline is kept; newly extracted entries are appended after dedup.

Conflict + certainty metadata:
  _conflicts  — list of {field, db_value, extracted_value, confidence}
  _low_confidence — list of {field, value, confidence}
  _db_seeded_fields — set of field paths pre-filled from DB (read-only)
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Demographics ──────────────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


class InsuranceInfo(BaseModel):
    provider: Optional[str] = None
    policy_number: Optional[str] = None
    group_number: Optional[str] = None
    subscriber_name: Optional[str] = None


class EmergencyContact(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None
    phone: Optional[str] = None


class Demographics(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    gender: Optional[str] = None
    mrn: Optional[str] = None
    contact_info: ContactInfo = Field(default_factory=ContactInfo)
    insurance: InsuranceInfo = Field(default_factory=InsuranceInfo)
    emergency_contact: EmergencyContact = Field(default_factory=EmergencyContact)
    confidence: Optional[float] = None


# ── Chief Complaint ───────────────────────────────────────────────────────────

class ChiefComplaint(BaseModel):
    free_text: Optional[str] = None
    onset: Optional[str] = None
    duration: Optional[str] = None
    severity: Optional[str] = None      # e.g. "7/10"
    location: Optional[str] = None
    confidence: Optional[float] = None


# ── History of Present Illness ────────────────────────────────────────────────

class HPIEvent(BaseModel):
    symptom: str
    onset: Optional[str] = None
    progression: Optional[str] = None   # "improving", "worsening", "stable"
    triggers: Optional[str] = None
    relieving_factors: Optional[str] = None
    associated_symptoms: Optional[str] = None
    timeline: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: Optional[float] = None


# ── Past Medical History ─────────────────────────────────────────────────────

class ChronicCondition(BaseModel):
    name: str
    icd10_code: Optional[str] = None
    onset_year: Optional[str] = None
    status: Optional[str] = None        # "active", "resolved", "controlled"
    source: Optional[str] = None        # "transcript", "document", "prior_record"
    confidence: Optional[float] = None


class Hospitalization(BaseModel):
    reason: Optional[str] = None
    date: Optional[str] = None
    facility: Optional[str] = None
    duration: Optional[str] = None
    confidence: Optional[float] = None


class Surgery(BaseModel):
    name: str
    date: Optional[str] = None
    facility: Optional[str] = None
    confidence: Optional[float] = None


class PastMedicalHistory(BaseModel):
    chronic_conditions: List[ChronicCondition] = Field(default_factory=list)
    hospitalizations: List[Hospitalization] = Field(default_factory=list)
    surgeries: List[Surgery] = Field(default_factory=list)
    prior_diagnoses: List[str] = Field(default_factory=list)


# ── Medications ───────────────────────────────────────────────────────────────

class Medication(BaseModel):
    name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    indication: Optional[str] = None
    start_date: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None


# ── Allergies ─────────────────────────────────────────────────────────────────

class Allergy(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: Optional[str] = None     # "mild", "moderate", "anaphylaxis"
    category: Optional[str] = None     # "drug", "food", "environmental"
    source: Optional[str] = None
    confidence: Optional[float] = None


# ── Family History ────────────────────────────────────────────────────────────

class FamilyHistoryEntry(BaseModel):
    member: str                         # "mother", "father", "sibling", "child"
    conditions: List[str] = Field(default_factory=list)
    alive: Optional[bool] = None
    age_at_death: Optional[str] = None
    cause_of_death: Optional[str] = None
    confidence: Optional[float] = None


# ── Social History ────────────────────────────────────────────────────────────

class SocialHistory(BaseModel):
    tobacco: Optional[str] = None       # "never", "former 10 pack-years", "current 1ppd"
    alcohol: Optional[str] = None       # "none", "social", "heavy (>14 drinks/week)"
    drug_use: Optional[str] = None
    occupation: Optional[str] = None
    exercise: Optional[str] = None
    diet: Optional[str] = None
    sexual_activity: Optional[str] = None
    confidence: Optional[float] = None


# ── Review of Systems ─────────────────────────────────────────────────────────

class ReviewOfSystems(BaseModel):
    cardiovascular: Optional[str] = None   # "chest pain, palpitations"
    respiratory: Optional[str] = None
    neurological: Optional[str] = None
    gastrointestinal: Optional[str] = None
    musculoskeletal: Optional[str] = None
    dermatological: Optional[str] = None
    psychiatric: Optional[str] = None
    endocrine: Optional[str] = None
    genitourinary: Optional[str] = None
    hematologic: Optional[str] = None
    confidence: Optional[float] = None


# ── Vitals ────────────────────────────────────────────────────────────────────

class Vitals(BaseModel):
    blood_pressure: Optional[str] = None   # "120/80 mmHg"
    heart_rate: Optional[str] = None       # "72 bpm"
    respiratory_rate: Optional[str] = None # "16 /min"
    temperature: Optional[str] = None      # "98.6 °F"
    spo2: Optional[str] = None             # "98%"
    height: Optional[str] = None
    weight: Optional[str] = None
    bmi: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: Optional[float] = None


# ── Labs ──────────────────────────────────────────────────────────────────────

class LabResult(BaseModel):
    test: str
    value: Optional[str] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal: Optional[bool] = None
    date: Optional[str] = None
    confidence: Optional[float] = None


# ── Physical Exam ─────────────────────────────────────────────────────────────

class PhysicalExam(BaseModel):
    general: Optional[str] = None
    cardiovascular: Optional[str] = None
    respiratory: Optional[str] = None
    neurological: Optional[str] = None
    abdomen: Optional[str] = None
    musculoskeletal: Optional[str] = None
    skin: Optional[str] = None
    head_neck: Optional[str] = None
    confidence: Optional[float] = None


# ── Problem List ──────────────────────────────────────────────────────────────

class Problem(BaseModel):
    name: str
    status: Optional[str] = None        # "active", "resolved", "chronic"
    source: Optional[str] = None
    confidence: Optional[float] = None


# ── Risk Factors ──────────────────────────────────────────────────────────────

class RiskFactor(BaseModel):
    name: str
    severity: Optional[str] = None     # "low", "moderate", "high"
    source: Optional[str] = None       # "clinical", "self_report", "derived"
    confidence: Optional[float] = None


# ── Assessment ────────────────────────────────────────────────────────────────

class Assessment(BaseModel):
    likely_diagnoses: List[str] = Field(default_factory=list)
    differential_diagnoses: List[str] = Field(default_factory=list)
    clinical_reasoning: Optional[str] = None
    confidence: Optional[float] = None


# ── Plan ──────────────────────────────────────────────────────────────────────

class Plan(BaseModel):
    medications_prescribed: List[str] = Field(default_factory=list)
    tests_ordered: List[str] = Field(default_factory=list)
    lifestyle_recommendations: List[str] = Field(default_factory=list)
    follow_up: Optional[str] = None
    referrals: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None


# ── Diagnostic Intelligence ──────────────────────────────────────────────────

class RecommendedTest(BaseModel):
    test: str
    rationale: Optional[str] = None
    priority: Optional[str] = None          # "stat", "urgent", "routine"
    expected_finding: Optional[str] = None


class ClinicalRiskFlag(BaseModel):
    flag: str
    severity: Optional[str] = None          # "critical", "high", "moderate", "low"
    action: Optional[str] = None


class TreatmentGuidance(BaseModel):
    condition: str
    recommendation: Optional[str] = None
    evidence_level: Optional[str] = None    # "guideline", "expert_consensus", "empiric"
    precautions: List[str] = Field(default_factory=list)


class DiagnosticInsight(BaseModel):
    """Structured diagnosis entry with reasoning provenance."""
    name: str
    icd10: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    supporting_evidence: List[str] = Field(default_factory=list)
    against_evidence: List[str] = Field(default_factory=list)


class DiagnosticReasoning(BaseModel):
    """Output of the diagnostic reasoning pipeline node."""
    top_diagnoses: List[DiagnosticInsight] = Field(default_factory=list)
    recommended_tests: List[RecommendedTest] = Field(default_factory=list)
    risk_flags: List[ClinicalRiskFlag] = Field(default_factory=list)
    treatment_guidance: List[TreatmentGuidance] = Field(default_factory=list)
    specialty: Optional[str] = None
    reasoning_trace: Optional[str] = None
    method: Optional[str] = None            # "llm", "rule_based", "rule_fallback"


# ── Procedures / Diagnoses / Visit ────────────────────────────────────────────

class Diagnosis(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[float] = None


class Procedure(BaseModel):
    name: str
    date: Optional[str] = None
    confidence: Optional[float] = None


class Visit(BaseModel):
    date: Optional[str] = None
    type: Optional[str] = None
    location: Optional[str] = None
    provider: Optional[str] = None


# ── Top-level record ──────────────────────────────────────────────────────────

class StructuredRecord(BaseModel):
    # Core identifiers
    demographics: Demographics = Field(default_factory=Demographics)
    visit: Visit = Field(default_factory=Visit)

    # Clinical content — ordered as in a standard H&P
    chief_complaint: ChiefComplaint = Field(default_factory=ChiefComplaint)
    hpi: List[HPIEvent] = Field(default_factory=list)
    past_medical_history: PastMedicalHistory = Field(default_factory=PastMedicalHistory)
    medications: List[Medication] = Field(default_factory=list)
    allergies: List[Allergy] = Field(default_factory=list)
    family_history: List[FamilyHistoryEntry] = Field(default_factory=list)
    social_history: SocialHistory = Field(default_factory=SocialHistory)
    review_of_systems: ReviewOfSystems = Field(default_factory=ReviewOfSystems)
    vitals: Vitals = Field(default_factory=Vitals)
    physical_exam: PhysicalExam = Field(default_factory=PhysicalExam)
    labs: List[LabResult] = Field(default_factory=list)
    procedures: List[Procedure] = Field(default_factory=list)
    diagnoses: List[Diagnosis] = Field(default_factory=list)
    problem_list: List[Problem] = Field(default_factory=list)
    risk_factors: List[RiskFactor] = Field(default_factory=list)
    assessment: Assessment = Field(default_factory=Assessment)
    plan: Plan = Field(default_factory=Plan)

    # Diagnostic intelligence (populated by diagnostic_reasoning node)
    diagnostic_reasoning: DiagnosticReasoning = Field(default_factory=DiagnosticReasoning)

    # Metadata for rendering
    _conflicts: List[Dict[str, Any]] = []
    _low_confidence: List[Dict[str, Any]] = []
    _db_seeded_fields: List[str] = []

    # Legacy compatibility
    @property
    def patient(self) -> Dict[str, Any]:
        """Alias for backwards-compatible access."""
        d = self.demographics
        return {
            "name": d.full_name,
            "dob": d.date_of_birth,
            "sex": d.sex,
            "mrn": d.mrn,
        }


# ── Empty-record factory ──────────────────────────────────────────────────────

def empty_record() -> Dict[str, Any]:
    """Return an empty mutable dict matching the StructuredRecord shape."""
    return {
        "demographics": {
            "full_name": None,
            "date_of_birth": None,
            "age": None,
            "sex": None,
            "gender": None,
            "mrn": None,
            "contact_info": {"phone": None, "email": None, "address": None, "city": None, "state": None, "zip": None},
            "insurance": {"provider": None, "policy_number": None, "group_number": None, "subscriber_name": None},
            "emergency_contact": {"name": None, "relationship": None, "phone": None},
        },
        "visit": {"date": None, "type": None, "location": None, "provider": None},
        "chief_complaint": {"free_text": None, "onset": None, "duration": None, "severity": None, "location": None},
        "hpi": [],
        "past_medical_history": {
            "chronic_conditions": [],
            "hospitalizations": [],
            "surgeries": [],
            "prior_diagnoses": [],
        },
        "medications": [],
        "allergies": [],
        "family_history": [],
        "social_history": {
            "tobacco": None, "alcohol": None, "drug_use": None,
            "occupation": None, "exercise": None, "diet": None, "sexual_activity": None,
        },
        "review_of_systems": {
            "cardiovascular": None, "respiratory": None, "neurological": None,
            "gastrointestinal": None, "musculoskeletal": None, "dermatological": None,
            "psychiatric": None, "endocrine": None, "genitourinary": None, "hematologic": None,
        },
        "vitals": {
            "blood_pressure": None, "heart_rate": None, "respiratory_rate": None,
            "temperature": None, "spo2": None, "height": None, "weight": None,
            "bmi": None, "timestamp": None,
        },
        "physical_exam": {
            "general": None, "cardiovascular": None, "respiratory": None,
            "neurological": None, "abdomen": None, "musculoskeletal": None,
            "skin": None, "head_neck": None,
        },
        "labs": [],
        "procedures": [],
        "diagnoses": [],
        "problem_list": [],
        "risk_factors": [],
        "assessment": {"likely_diagnoses": [], "differential_diagnoses": [], "clinical_reasoning": None},
        "plan": {
            "medications_prescribed": [], "tests_ordered": [],
            "lifestyle_recommendations": [], "follow_up": None, "referrals": [],
        },        # Diagnostic intelligence (from diagnostic_reasoning node)
        "diagnostic_reasoning": {
            "top_diagnoses": [],
            "recommended_tests": [],
            "risk_flags": [],
            "treatment_guidance": [],
            "specialty": None,
            "reasoning_trace": None,
            "method": None,
        },        # Metadata — not rendered as medical content
        "_conflicts": [],
        "_low_confidence": [],
        "_db_seeded_fields": [],
    }

