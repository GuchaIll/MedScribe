"""
Clinical Suggestion Engine for Decision Support.

Provides real-time clinical suggestions based on patient history:
- Allergy-medication conflict checking
- Drug-drug interaction detection (local rules + optional RxNorm API)
- Contraindication warnings (local rules + optional FDA label data)
- Dosage appropriateness based on age, weight, BMI, renal function
- Historical context for clinical decisions
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)


class ClinicalSuggestionEngine:
    """
    Engine for generating clinical decision support suggestions.

    Analyzes current medical record against patient history to identify:
    - Medication-allergy conflicts (with cross-reactivity)
    - Drug-drug interactions (local rules + optional RxNorm)
    - Contraindications (local rules + optional FDA labels)
    - Dosage issues based on patient parameters (age, weight, renal function)
    - Relevant historical context

    Usage:
        # Local rules only (default, no external API calls)
        engine = ClinicalSuggestionEngine()

        # With external API integration (RxNorm + OpenFDA)
        engine = ClinicalSuggestionEngine(use_external_database=True)

        # With DrugBank (requires API key)
        engine = ClinicalSuggestionEngine(
            use_external_database=True,
            drugbank_api_key="your_key"
        )
    """

    # -------------------------------------------------------------------------
    # Cross-reactivity map: allergen_class -> list of medications to avoid
    # -------------------------------------------------------------------------
    MEDICATION_ALLERGY_MAP = {
        "penicillin": ["amoxicillin", "ampicillin", "penicillin", "augmentin",
                       "amoxicillin-clavulanate", "dicloxacillin", "oxacillin",
                       "nafcillin", "piperacillin", "ticarcillin"],
        "cephalosporin": ["cephalexin", "cefazolin", "ceftriaxone", "cefdinir",
                          "cefprozil", "cefuroxime", "cefepime", "ceftazidime"],
        "sulfa": ["sulfamethoxazole", "trimethoprim", "bactrim", "septra",
                  "sulfadiazine", "sulfasalazine", "furosemide", "hydrochlorothiazide"],
        "aspirin": ["aspirin", "asa", "acetylsalicylic"],
        "nsaid": ["ibuprofen", "naproxen", "diclofenac", "celecoxib",
                  "indomethacin", "ketorolac", "meloxicam", "piroxicam"],
        "codeine": ["codeine", "oxycodone", "hydrocodone", "morphine",
                    "hydromorphone", "fentanyl", "tramadol"],
        "fluoroquinolone": ["ciprofloxacin", "levofloxacin", "moxifloxacin",
                            "ofloxacin", "norfloxacin"],
        "macrolide": ["azithromycin", "clarithromycin", "erythromycin"],
        "tetracycline": ["doxycycline", "minocycline", "tetracycline"],
        "latex": [],
        "shellfish": [],
        "peanut": [],
        "contrast": ["iohexol", "iopamidol", "iodixanol"],
    }

    # -------------------------------------------------------------------------
    # Drug class aliases: normalized drug name -> class key used in DRUG_INTERACTIONS
    # and CONTRAINDICATIONS tables.
    # -------------------------------------------------------------------------
    DRUG_CLASS_ALIASES: Dict[str, str] = {
        # ACE inhibitors
        "lisinopril":      "ace_inhibitor",
        "enalapril":       "ace_inhibitor",
        "ramipril":        "ace_inhibitor",
        "captopril":       "ace_inhibitor",
        "benazepril":      "ace_inhibitor",
        "fosinopril":      "ace_inhibitor",
        "quinapril":       "ace_inhibitor",
        # ARBs
        "losartan":        "arb",
        "valsartan":       "arb",
        "irbesartan":      "arb",
        "candesartan":     "arb",
        "olmesartan":      "arb",
        "telmisartan":     "arb",
        # NSAIDs
        "ibuprofen":       "nsaid",
        "naproxen":        "nsaid",
        "diclofenac":      "nsaid",
        "celecoxib":       "nsaid",
        "indomethacin":    "nsaid",
        "ketorolac":       "nsaid",
        "meloxicam":       "nsaid",
        "piroxicam":       "nsaid",
        "sulindac":        "nsaid",
        # SSRIs
        "sertraline":      "ssri",
        "fluoxetine":      "ssri",
        "paroxetine":      "ssri",
        "escitalopram":    "ssri",
        "citalopram":      "ssri",
        "fluvoxamine":     "ssri",
        # MAOIs
        "phenelzine":      "maoi",
        "tranylcypromine": "maoi",
        "isocarboxazid":   "maoi",
        "selegiline":      "maoi",
        # Statins
        "simvastatin":     "statins",
        "atorvastatin":    "statins",
        "rosuvastatin":    "statins",
        "pravastatin":     "statins",
        "lovastatin":      "statins",
        "fluvastatin":     "statins",
        "pitavastatin":    "statins",
        # Beta-blockers
        "metoprolol":      "beta_blocker",
        "atenolol":        "beta_blocker",
        "carvedilol":      "beta_blocker",
        "propranolol":     "beta_blocker",
        "bisoprolol":      "beta_blocker",
        "labetalol":       "beta_blocker",
        "nebivolol":       "beta_blocker",
        # Fluoroquinolones
        "ciprofloxacin":   "fluoroquinolone",
        "levofloxacin":    "fluoroquinolone",
        "moxifloxacin":    "fluoroquinolone",
        "ofloxacin":       "fluoroquinolone",
        # Macrolides
        "clarithromycin":  "macrolide",
        "azithromycin":    "macrolide",
        "erythromycin":    "macrolide",
        # Thiazolidinediones
        "pioglitazone":    "thiazolidinedione",
        "rosiglitazone":   "thiazolidinedione",
    }

    # Drugs that belong to multiple interaction-table classes
    DRUG_EXTRA_CLASSES: Dict[str, List[str]] = {
        "ciprofloxacin": ["fluoroquinolone", "quinolone"],
        "levofloxacin":  ["fluoroquinolone", "quinolone"],
        "moxifloxacin":  ["fluoroquinolone", "quinolone"],
        "ofloxacin":     ["fluoroquinolone", "quinolone"],
    }

    # -------------------------------------------------------------------------
    # Drug-drug interactions: (drug_a, drug_b) -> interaction details
    # Both keys are normalized (lowercase, no dosage)
    # -------------------------------------------------------------------------
    DRUG_INTERACTIONS = {
        ("warfarin", "aspirin"): {
            "severity": "major",
            "effect": "Significantly increased bleeding risk",
            "recommendation": "Monitor INR closely. Consider GI prophylaxis (PPI)."
        },
        ("warfarin", "nsaid"): {
            "severity": "major",
            "effect": "Increased bleeding risk",
            "recommendation": "Avoid combination if possible. Use acetaminophen instead."
        },
        ("warfarin", "amiodarone"): {
            "severity": "major",
            "effect": "Warfarin potentiation — INR can double or triple",
            "recommendation": "Reduce warfarin dose by 30-50%. Monitor INR weekly."
        },
        ("warfarin", "fluconazole"): {
            "severity": "major",
            "effect": "CYP2C9 inhibition markedly increases warfarin effect",
            "recommendation": "Reduce warfarin dose. Monitor INR every 2-3 days."
        },
        ("warfarin", "metronidazole"): {
            "severity": "major",
            "effect": "Increased anticoagulation",
            "recommendation": "Monitor INR closely during and after metronidazole course."
        },
        ("metformin", "contrast"): {
            "severity": "major",
            "effect": "Risk of lactic acidosis with iodinated contrast",
            "recommendation": "Hold metformin 48h before and after contrast. Recheck renal function before restarting."
        },
        ("digoxin", "amiodarone"): {
            "severity": "major",
            "effect": "Amiodarone increases digoxin levels 1.5-2x (digoxin toxicity risk)",
            "recommendation": "Reduce digoxin dose by 50%. Monitor digoxin levels and for toxicity (nausea, visual changes)."
        },
        ("digoxin", "clarithromycin"): {
            "severity": "major",
            "effect": "P-glycoprotein inhibition increases digoxin levels",
            "recommendation": "Reduce digoxin dose. Monitor levels during antibiotic course."
        },
        ("ace_inhibitor", "potassium"): {
            "severity": "moderate",
            "effect": "Additive hyperkalemia risk",
            "recommendation": "Monitor potassium levels. Avoid potassium supplements unless clearly indicated."
        },
        ("ace_inhibitor", "spironolactone"): {
            "severity": "moderate",
            "effect": "Increased hyperkalemia risk",
            "recommendation": "Monitor potassium and renal function. Use lowest effective doses."
        },
        ("ssri", "tramadol"): {
            "severity": "major",
            "effect": "Serotonin syndrome risk",
            "recommendation": "Avoid combination. Use alternative analgesic."
        },
        ("ssri", "maoi"): {
            "severity": "major",
            "effect": "Serotonin syndrome — potentially life-threatening",
            "recommendation": "Contraindicated. Allow 14-day washout between agents."
        },
        ("statins", "amiodarone"): {
            "severity": "moderate",
            "effect": "Increased statin levels and myopathy risk",
            "recommendation": "Limit simvastatin to 20mg/day. Prefer pravastatin or rosuvastatin."
        },
        ("statins", "clarithromycin"): {
            "severity": "major",
            "effect": "CYP3A4 inhibition markedly increases statin levels — rhabdomyolysis risk",
            "recommendation": "Temporarily hold statin during clarithromycin course, or use non-CYP3A4 statin."
        },
        ("clopidogrel", "omeprazole"): {
            "severity": "moderate",
            "effect": "CYP2C19 inhibition reduces clopidogrel activation",
            "recommendation": "Consider pantoprazole or famotidine instead of omeprazole."
        },
        ("lithium", "nsaid"): {
            "severity": "major",
            "effect": "NSAIDs reduce renal lithium clearance — toxicity risk",
            "recommendation": "Avoid NSAIDs. Use acetaminophen for analgesia. Monitor lithium levels."
        },
        ("lithium", "ace_inhibitor"): {
            "severity": "major",
            "effect": "ACE inhibitors increase lithium levels",
            "recommendation": "Monitor lithium levels closely when starting/stopping ACE inhibitor."
        },
        ("methotrexate", "nsaid"): {
            "severity": "major",
            "effect": "NSAIDs reduce methotrexate clearance — serious toxicity risk",
            "recommendation": "Avoid combination. Use alternative analgesic."
        },
        ("quinolone", "antacids"): {
            "severity": "moderate",
            "effect": "Divalent cations (Mg, Al, Ca) chelate quinolones and reduce absorption",
            "recommendation": "Separate administration by at least 2 hours."
        },
    }

    # -------------------------------------------------------------------------
    # Contraindications: (medication_key, condition_key) -> details
    # Keys are partial strings matched against normalized names/conditions
    # -------------------------------------------------------------------------
    CONTRAINDICATIONS = {
        ("metformin", "renal"): {
            "severity": "major",
            "reason": "Risk of life-threatening lactic acidosis in renal impairment",
            "recommendation": "Contraindicated if eGFR < 30. Use with caution if eGFR 30-45 (reduce dose)."
        },
        ("metformin", "kidney"): {
            "severity": "major",
            "reason": "Risk of lactic acidosis in kidney disease",
            "recommendation": "Check eGFR. Contraindicated if eGFR < 30."
        },
        ("nsaid", "heart failure"): {
            "severity": "major",
            "reason": "NSAIDs cause sodium retention and can precipitate acute decompensation",
            "recommendation": "Avoid NSAIDs. Use acetaminophen for analgesia."
        },
        ("nsaid", "peptic ulcer"): {
            "severity": "moderate",
            "reason": "NSAIDs inhibit COX-1 and increase GI bleeding risk",
            "recommendation": "Avoid NSAIDs or use with PPI gastroprotection."
        },
        ("nsaid", "chronic kidney"): {
            "severity": "major",
            "reason": "NSAIDs impair renal prostaglandins and worsen renal function",
            "recommendation": "Avoid NSAIDs. Use acetaminophen."
        },
        ("beta_blocker", "asthma"): {
            "severity": "moderate",
            "reason": "Non-selective beta-blockers can cause bronchospasm",
            "recommendation": "Use cardioselective beta-blocker (metoprolol, atenolol) with caution."
        },
        ("beta_blocker", "copd"): {
            "severity": "moderate",
            "reason": "Beta-blockers may worsen bronchospasm in COPD",
            "recommendation": "Use cardioselective agent at lowest effective dose."
        },
        ("ace_inhibitor", "pregnancy"): {
            "severity": "major",
            "reason": "ACE inhibitors are teratogenic — fetal renal dysgenesis",
            "recommendation": "Contraindicated in pregnancy. Switch to labetalol or nifedipine."
        },
        ("arb", "pregnancy"): {
            "severity": "major",
            "reason": "ARBs are teratogenic — similar to ACE inhibitors",
            "recommendation": "Contraindicated in pregnancy. Switch to methyldopa or labetalol."
        },
        ("fluoroquinolone", "myasthenia"): {
            "severity": "major",
            "reason": "Fluoroquinolones can exacerbate myasthenia gravis",
            "recommendation": "Avoid fluoroquinolones. Use alternative antibiotic."
        },
        ("warfarin", "pregnancy"): {
            "severity": "major",
            "reason": "Warfarin crosses the placenta and is teratogenic",
            "recommendation": "Switch to low molecular weight heparin during pregnancy."
        },
        ("statins", "pregnancy"): {
            "severity": "major",
            "reason": "Statins are teratogenic (lipid-lowering not needed in pregnancy)",
            "recommendation": "Discontinue statins during pregnancy."
        },
        ("thiazolidinedione", "heart failure"): {
            "severity": "major",
            "reason": "Thiazolidinediones (pioglitazone, rosiglitazone) cause fluid retention",
            "recommendation": "Contraindicated in NYHA Class III-IV heart failure."
        },
        ("digoxin", "hypokalemia"): {
            "severity": "major",
            "reason": "Hypokalemia increases myocardial sensitivity to digoxin toxicity",
            "recommendation": "Correct potassium before starting/continuing digoxin."
        },
    }

    def __init__(
        self,
        use_external_database: bool = False,
        drugbank_api_key: Optional[str] = None
    ):
        """
        Initialize clinical suggestion engine.

        Args:
            use_external_database: Enable RxNorm + OpenFDA API calls for enhanced
                                   interaction and warning data. Defaults to False
                                   to keep unit tests fast and offline-capable.
            drugbank_api_key: Optional DrugBank API key for commercial drug data.
        """
        self.use_external_database = use_external_database

        # Lazy-import heavy dependencies only when needed
        self._dosage_calculator = None
        self._drug_client = None

        if use_external_database:
            self._init_external_clients(drugbank_api_key)

    def _init_external_clients(self, drugbank_api_key: Optional[str]):
        """Initialize external API clients (called only when enabled)."""
        try:
            from .dosage_calculator import get_dosage_calculator
            self._dosage_calculator = get_dosage_calculator()
        except ImportError:
            logger.warning("dosage_calculator module not available")

        try:
            from .drug_database_client import get_drug_database_client
            self._drug_client = get_drug_database_client(
                drugbank_api_key=drugbank_api_key
            )
        except ImportError:
            logger.warning("drug_database_client module not available")

    @property
    def dosage_calculator(self):
        """Lazy-load dosage calculator."""
        if self._dosage_calculator is None:
            from .dosage_calculator import get_dosage_calculator
            self._dosage_calculator = get_dosage_calculator()
        return self._dosage_calculator

    # =========================================================================
    # Public API
    # =========================================================================

    def generate_suggestions(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate clinical suggestions based on current record and patient history.

        Args:
            current_record: Current medical record being created. Expected keys:
                - patient: {age, sex, weight_kg, height_cm, ...}
                - medications: [{name, dose, route, frequency}, ...]
                - diagnoses: [{description, code, status}, ...]
                - labs: [{test_name, value, unit, abnormal}, ...]
                - vital_signs: {weight, height, ...}
            patient_history: Patient's historical data from patient_service. Expected keys:
                - allergies: [{substance, reaction, severity}, ...]
                - medications: [{name, status, start_date}, ...]
                - diagnoses: [{description, status, first_recorded}, ...]
                - labs: [{test_name, value, abnormal, date}, ...]
                - procedures: [{name, date}, ...]

        Returns:
            Dictionary with clinical suggestions:
                - allergy_alerts: critical alerts for allergy conflicts
                - drug_interactions: interaction warnings (local + API if enabled)
                - contraindications: medication-condition conflicts
                - dosage_alerts: patient-parameter-based dosing issues
                - fda_warnings: FDA label warnings (if external DB enabled)
                - historical_context: relevant patient history summary
                - risk_level: "critical" | "high" | "moderate" | "low"
                - timestamp: ISO timestamp
        """
        suggestions = {
            "allergy_alerts": self._check_allergies(current_record, patient_history),
            "drug_interactions": self._check_drug_interactions(current_record, patient_history),
            "contraindications": self._check_contraindications(current_record, patient_history),
            "dosage_alerts": self._check_dosage_appropriateness(current_record, patient_history),
            "historical_context": self._provide_context(patient_history),
            "timestamp": datetime.now().isoformat()
        }

        # Enrich with external database data if enabled
        if self.use_external_database and self._drug_client:
            suggestions["drug_interactions"] = self._enrich_interactions_from_api(
                suggestions["drug_interactions"],
                current_record,
                patient_history
            )
            suggestions["fda_warnings"] = self._get_fda_warnings(
                current_record.get("medications", [])
            )
        else:
            suggestions["fda_warnings"] = []

        suggestions["risk_level"] = self._calculate_risk_level(suggestions)

        return suggestions

    # =========================================================================
    # Allergy Checking
    # =========================================================================

    def _check_allergies(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Check prescribed medications against known patient allergies."""
        alerts = []
        current_meds = current_record.get("medications", [])
        known_allergies = patient_history.get("allergies", [])

        if not current_meds or not known_allergies:
            return alerts

        for med in current_meds:
            med_name = self._normalize_medication_name(med.get("name", ""))
            if not med_name:
                continue

            for allergy in known_allergies:
                allergen = self._normalize_medication_name(allergy.get("substance", ""))
                if not allergen:
                    continue

                if self._is_related_substance(med_name, allergen):
                    cross_reactive = allergen not in med_name and med_name not in allergen
                    alerts.append({
                        "severity": "critical",
                        "type": "allergy_conflict",
                        "medication": med.get("name"),
                        "allergen": allergy.get("substance"),
                        "reaction": allergy.get("reaction", "Unknown"),
                        "allergy_severity": allergy.get("severity", "Unknown"),
                        "cross_reactive": cross_reactive,
                        "message": (
                            f"CROSS-REACTIVITY ALERT: {med.get('name')} may cross-react "
                            f"with documented {allergy.get('substance')} allergy"
                            if cross_reactive else
                            f"ALLERGY ALERT: Patient allergic to {allergy.get('substance')} "
                            f"— prescribed {med.get('name')}"
                        ),
                        "recommendation": (
                            "Review cross-reactivity. Consider alternative medication."
                            if cross_reactive else
                            "Contraindicated. Prescribe alternative medication."
                        )
                    })

        return alerts

    # =========================================================================
    # Drug-Drug Interaction Checking
    # =========================================================================

    def _check_drug_interactions(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Check for drug-drug interactions using local rule base."""
        current_meds = current_record.get("medications", [])
        if not current_meds:
            return []

        active_history_meds = [
            m for m in patient_history.get("medications", [])
            if m.get("status") == "active"
        ]

        all_meds = list({
            self._normalize_medication_name(m.get("name", ""))
            for m in (current_meds + active_history_meds)
            if m.get("name")
        })

        interactions = []
        for i, med1 in enumerate(all_meds):
            for med2 in all_meds[i + 1:]:
                result = self._find_interaction(med1, med2)
                if result:
                    interactions.append({
                        "severity": result["severity"],
                        "type": "drug_interaction",
                        "medication1": med1,
                        "medication2": med2,
                        "effect": result["effect"],
                        "recommendation": result["recommendation"],
                        "source": "local_rules",
                        "message": f"INTERACTION: {med1} + {med2} — {result['effect']}"
                    })

        return interactions

    def _enrich_interactions_from_api(
        self,
        local_interactions: List[Dict],
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> List[Dict]:
        """
        Augment local interaction results with RxNorm API data.
        Deduplicates against existing local results.
        """
        all_interactions = list(local_interactions)
        seen_pairs = {
            (i["medication1"], i["medication2"]) for i in local_interactions
        }

        current_meds = current_record.get("medications", [])
        active_history_meds = [
            m for m in patient_history.get("medications", [])
            if m.get("status") == "active"
        ]
        all_med_names = [m.get("name", "") for m in (current_meds + active_history_meds) if m.get("name")]

        for med_name in all_med_names:
            try:
                api_interactions = self._drug_client.get_drug_interactions(med_name)
                for interaction in api_interactions:
                    drug2 = interaction.get("drug2", "")
                    # Only add if the second drug is in patient's medication list
                    if not self._patient_on_drug(drug2, all_med_names):
                        continue

                    pair = (interaction.get("drug1", "").lower(), drug2.lower())
                    pair_rev = (pair[1], pair[0])

                    if pair not in seen_pairs and pair_rev not in seen_pairs:
                        seen_pairs.add(pair)
                        all_interactions.append({
                            "severity": interaction.get("severity", "moderate"),
                            "type": "drug_interaction",
                            "medication1": interaction.get("drug1", ""),
                            "medication2": drug2,
                            "effect": interaction.get("description", ""),
                            "recommendation": "Review interaction. Consult pharmacist if needed.",
                            "source": "rxnorm_api",
                            "message": f"INTERACTION (RxNorm): {interaction.get('drug1')} + {drug2}"
                        })
            except Exception as e:
                logger.warning(f"RxNorm API error for {med_name}: {e}")
                continue

        return all_interactions

    # =========================================================================
    # Contraindication Checking
    # =========================================================================

    def _check_contraindications(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Check medication-condition contraindications from local rule base."""
        contraindications = []
        current_meds = current_record.get("medications", [])
        if not current_meds:
            return contraindications

        all_diagnoses = (
            patient_history.get("diagnoses", []) +
            current_record.get("diagnoses", [])
        )
        active_diagnoses = [d for d in all_diagnoses if d.get("status") == "active"]
        if not active_diagnoses:
            return contraindications

        for med in current_meds:
            med_name = self._normalize_medication_name(med.get("name", ""))

            for diagnosis in active_diagnoses:
                condition = diagnosis.get("description", "").lower()
                result = self._find_contraindication(med_name, condition)
                if result:
                    contraindications.append({
                        "severity": result["severity"],
                        "type": "contraindication",
                        "medication": med.get("name"),
                        "condition": diagnosis.get("description"),
                        "reason": result["reason"],
                        "recommendation": result["recommendation"],
                        "message": (
                            f"CONTRAINDICATION: {med.get('name')} with "
                            f"{diagnosis.get('description')}"
                        )
                    })

        return contraindications

    # =========================================================================
    # Dosage Appropriateness Checking
    # =========================================================================

    def _check_dosage_appropriateness(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Check dosage appropriateness using patient parameters.

        Evaluates:
        - Renal function (CrCl/eGFR from labs or calculated from creatinine)
        - Age (geriatric Beers Criteria, pediatric weight-based)
        - Weight/BMI extremes
        """
        alerts = []
        current_meds = current_record.get("medications", [])
        if not current_meds:
            return alerts

        patient_params = self._extract_patient_params(current_record, patient_history)
        if not patient_params:
            return alerts

        for med in current_meds:
            try:
                result = self.dosage_calculator.check_dosage_appropriateness(
                    med, patient_params
                )
                for issue in result.get("issues", []):
                    alerts.append({
                        "medication": med.get("name"),
                        "type": issue["type"],
                        "severity": issue["severity"],
                        "message": issue["message"],
                        "recommendation": issue["recommendation"],
                        "calculated_params": result.get("calculated_params", {})
                    })
            except Exception as e:
                logger.warning(f"Dosage check failed for {med.get('name')}: {e}")

        return alerts

    def _extract_patient_params(
        self,
        current_record: Dict[str, Any],
        patient_history: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Build the patient parameter dict needed by DosageCalculator.

        Sources (in priority order):
          1. current_record["patient"] for age/sex
          2. current_record["vital_signs"] for weight/height
          3. current_record["labs"] for creatinine/eGFR
          4. patient_history["labs"] (recent labs) for renal function
        """
        patient = current_record.get("patient", {})
        age = patient.get("age")
        sex = patient.get("sex", "M")

        if age is None:
            return None  # Cannot do any meaningful checks without age

        params: Dict[str, Any] = {"age": int(age), "sex": sex, "labs": {}}

        # Weight from vital signs
        vitals = current_record.get("vital_signs", {})
        weight_raw = vitals.get("weight") or patient.get("weight")
        height_raw = vitals.get("height") or patient.get("height")

        if weight_raw:
            params["weight_kg"] = self._parse_numeric(weight_raw)
        if height_raw:
            params["height_cm"] = self._parse_numeric(height_raw)

        # Labs: creatinine and eGFR from current record first, then history
        all_labs = current_record.get("labs", []) + patient_history.get("labs", [])
        for lab in all_labs:
            test = lab.get("test_name", "").lower()
            value = lab.get("value")
            if value is None:
                continue
            if "creatinine" in test and "serum_creatinine" not in params:
                parsed = self._parse_numeric(str(value))
                if parsed:
                    params["serum_creatinine"] = parsed
            elif ("egfr" in test or "gfr" in test) and "egfr" not in params.get("labs", {}):
                parsed = self._parse_numeric(str(value))
                if parsed:
                    params["labs"]["egfr"] = parsed

        return params

    # =========================================================================
    # External API: FDA Warnings
    # =========================================================================

    def _get_fda_warnings(self, medications: List[Dict]) -> List[Dict]:
        """
        Retrieve FDA label warnings from OpenFDA for the current medications.
        Called only when use_external_database=True.
        """
        warnings = []
        for med in medications:
            try:
                label = self._drug_client.get_drug_label(med.get("name", ""))
                if not label or not label.get("warnings"):
                    continue

                warning_text = " ".join(label["warnings"])
                is_black_box = any(kw in warning_text.upper() for kw in ["BLACK BOX", "BOXED WARNING"])

                warnings.append({
                    "medication": med.get("name"),
                    "severity": "critical" if is_black_box else "moderate",
                    "type": "fda_black_box" if is_black_box else "fda_warning",
                    "message": (
                        f"FDA Black Box Warning for {med.get('name')}"
                        if is_black_box else
                        f"FDA safety warning for {med.get('name')}"
                    ),
                    "details": warning_text[:600],
                    "source": "fda_label"
                })
            except Exception as e:
                logger.warning(f"OpenFDA error for {med.get('name')}: {e}")

        return warnings

    # =========================================================================
    # Historical Context
    # =========================================================================

    def _provide_context(self, patient_history: Dict[str, Any]) -> Dict[str, Any]:
        """Summarise relevant historical data for the clinician."""
        context: Dict[str, Any] = {
            "chronic_conditions": [],
            "recent_procedures": [],
            "medication_changes": [],
            "recent_labs": []
        }

        for diagnosis in patient_history.get("diagnoses", []):
            if diagnosis.get("status") == "active":
                context["chronic_conditions"].append({
                    "condition": diagnosis.get("description"),
                    "code": diagnosis.get("code"),
                    "duration": self._calculate_duration(diagnosis.get("first_recorded"))
                })

        context["recent_procedures"] = patient_history.get("procedures", [])[:5]

        for lab in patient_history.get("labs", [])[:10]:
            if lab.get("abnormal"):
                context["recent_labs"].append({
                    "test": lab.get("test_name"),
                    "value": lab.get("value"),
                    "reference": lab.get("reference_range"),
                    "date": lab.get("date")
                })

        return context

    # =========================================================================
    # Risk Level
    # =========================================================================

    def _calculate_risk_level(self, suggestions: Dict[str, Any]) -> str:
        """
        Calculate overall risk level from all suggestion categories.

        Priority:
          critical: Any critical-severity allergy alert, dosage issue, or FDA black box warning
          high:     Major drug-drug interaction, or major dosage issue
          moderate: Any contraindication, moderate interaction, or dosage alert
          low:      No significant issues found
        """
        allergy_alerts = suggestions.get("allergy_alerts", [])
        drug_interactions = suggestions.get("drug_interactions", [])
        contraindications = suggestions.get("contraindications", [])
        dosage_alerts = suggestions.get("dosage_alerts", [])
        fda_warnings = suggestions.get("fda_warnings", [])

        def _has(lst, severity):
            return any(a.get("severity") == severity for a in lst)

        # Critical
        if (
            _has(allergy_alerts, "critical") or
            _has(dosage_alerts, "critical") or
            _has(fda_warnings, "critical")
        ):
            return "critical"

        # High
        if (
            _has(drug_interactions, "major") or
            _has(dosage_alerts, "major") or
            _has(contraindications, "major")
        ):
            return "high"

        # Moderate
        if (
            contraindications or
            drug_interactions or
            dosage_alerts or
            _has(fda_warnings, "moderate")
        ):
            return "moderate"

        return "low"

    # =========================================================================
    # Helpers
    # =========================================================================

    def _normalize_medication_name(self, name: str) -> str:
        """Strip dosage, route, and frequency from a medication name."""
        if not name:
            return ""
        name = re.sub(r'\d+\s*(mg|mcg|g|ml|units?)', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(po|iv|im|sq|sc|sl|pr)\b', '', name, flags=re.IGNORECASE)
        return name.strip().lower()

    def _is_related_substance(self, medication: str, allergen: str) -> bool:
        """True if medication is the same as or cross-reacts with the allergen."""
        # Direct match or substring match
        if medication == allergen or allergen in medication or medication in allergen:
            return True

        # Cross-reactivity via MEDICATION_ALLERGY_MAP
        for allergen_class, class_members in self.MEDICATION_ALLERGY_MAP.items():
            allergen_in_class = (allergen == allergen_class or allergen in class_members)
            med_in_class = (medication == allergen_class or medication in class_members)
            if allergen_in_class and med_in_class:
                return True

        return False

    def _get_drug_classes(self, normalized_name: str) -> List[str]:
        """
        Return all lookup keys for a drug: its own name plus any class aliases.

        Example: "sertraline" → ["sertraline", "ssri"]
                 "ciprofloxacin" → ["ciprofloxacin", "fluoroquinolone", "quinolone"]
        """
        keys = [normalized_name]

        # Primary class alias
        if normalized_name in self.DRUG_CLASS_ALIASES:
            keys.append(self.DRUG_CLASS_ALIASES[normalized_name])

        # Extra classes (drugs in multiple categories)
        if normalized_name in self.DRUG_EXTRA_CLASSES:
            keys.extend(self.DRUG_EXTRA_CLASSES[normalized_name])

        # Substring match for aliases (e.g. "sertraline hcl" → "sertraline")
        for drug, cls in self.DRUG_CLASS_ALIASES.items():
            if drug in normalized_name and cls not in keys:
                keys.append(cls)

        return keys

    def _find_interaction(self, med1: str, med2: str) -> Optional[Dict[str, str]]:
        """
        Look up a drug-drug interaction using both specific names and class aliases.
        """
        classes1 = self._get_drug_classes(med1)
        classes2 = self._get_drug_classes(med2)

        for c1 in classes1:
            for c2 in classes2:
                if (c1, c2) in self.DRUG_INTERACTIONS:
                    return self.DRUG_INTERACTIONS[(c1, c2)]
                if (c2, c1) in self.DRUG_INTERACTIONS:
                    return self.DRUG_INTERACTIONS[(c2, c1)]

        return None

    def _find_contraindication(
        self, medication: str, condition: str
    ) -> Optional[Dict[str, str]]:
        """
        Look up a medication-condition contraindication using specific names and
        class aliases.
        """
        med_keys = self._get_drug_classes(medication)

        for med_key in med_keys:
            for (mk, ck), details in self.CONTRAINDICATIONS.items():
                if mk in med_key and ck in condition:
                    return details

        return None

    def _patient_on_drug(self, drug_name: str, all_med_names: List[str]) -> bool:
        """Return True if drug_name appears in the patient's medication list."""
        normalized_query = self._normalize_medication_name(drug_name)
        for name in all_med_names:
            if normalized_query in self._normalize_medication_name(name):
                return True
        return False

    def _parse_numeric(self, value: Any) -> Optional[float]:
        """Extract the first numeric value from a string like '70 kg' or '1.5'."""
        if isinstance(value, (int, float)):
            return float(value)
        try:
            match = re.search(r'[\d.]+', str(value))
            return float(match.group()) if match else None
        except Exception:
            return None

    def _calculate_duration(self, first_recorded: Optional[str]) -> Optional[str]:
        """Return a human-readable duration since first_recorded date."""
        if not first_recorded:
            return None
        try:
            first_date = datetime.fromisoformat(first_recorded)
            delta = datetime.now() - first_date
            years = delta.days // 365
            if years > 0:
                return f"{years} year{'s' if years != 1 else ''}"
            months = delta.days // 30
            if months > 0:
                return f"{months} month{'s' if months != 1 else ''}"
            return f"{delta.days} day{'s' if delta.days != 1 else ''}"
        except Exception:
            return None


def get_clinical_suggestion_engine(
    use_external_database: bool = False,
    drugbank_api_key: Optional[str] = None
) -> ClinicalSuggestionEngine:
    """
    Factory function to create a clinical suggestion engine.

    Args:
        use_external_database: Enable RxNorm + OpenFDA API enrichment.
        drugbank_api_key: Optional DrugBank API key.
    """
    return ClinicalSuggestionEngine(
        use_external_database=use_external_database,
        drugbank_api_key=drugbank_api_key
    )
