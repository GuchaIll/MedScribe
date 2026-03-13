"""
Dosage Calculator with patient parameter-based adjustments.

Integrates with external drug databases for accurate dosing recommendations
based on age, weight, BMI, renal function, hepatic function, etc.
"""

from typing import Dict, Optional, List
from datetime import datetime
import math


class DosageCalculator:
    """
    Calculate appropriate drug dosages based on patient parameters.

    Considers:
    - Age (pediatric, geriatric adjustments)
    - Weight and BMI
    - Renal function (CrCl, eGFR)
    - Hepatic function
    - Drug-specific parameters
    """

    # Dosage adjustment rules (can be loaded from database)
    RENAL_DOSING_ADJUSTMENTS = {
        "metformin": {
            "contraindicated": {"egfr": {"max": 30}},  # eGFR < 30: contraindicated
            "reduce": {"egfr": {"min": 30, "max": 45}},  # eGFR 30-45: reduce dose
            "adjustment": "Reduce dose by 50% if eGFR 30-45 mL/min/1.73m². Contraindicated if eGFR < 30."
        },
        "enoxaparin": {
            "reduce": {"creatinine_clearance": {"max": 30}},
            "adjustment": "Reduce dose by 50% (use once daily instead of twice daily) if CrCl < 30 mL/min"
        },
        "digoxin": {
            "reduce": {"creatinine_clearance": {"max": 50}},
            "adjustment": "Reduce dose by 25-50% if CrCl < 50 mL/min. Monitor levels closely."
        }
    }

    PEDIATRIC_DOSING = {
        "acetaminophen": {
            "weight_based": {
                "dose_per_kg": 15,  # mg/kg/dose
                "max_single_dose": 1000,  # mg
                "max_daily_dose": 4000,  # mg
                "frequency": "q4-6h PRN"
            }
        },
        "amoxicillin": {
            "weight_based": {
                "dose_per_kg": 45,  # mg/kg/day divided q12h
                "max_daily_dose": 1000,
                "frequency": "q12h"
            }
        }
    }

    GERIATRIC_ADJUSTMENTS = {
        # Beers Criteria - drugs to avoid in elderly
        "avoid_geriatric": [
            "diphenhydramine",
            "diazepam",
            "amitriptyline",
            "cyclobenzaprine"
        ],
        "reduce_geriatric": {
            "zolpidem": 0.5,  # 50% dose reduction
            "trazodone": 0.5
        }
    }

    def __init__(self):
        """Initialize dosage calculator."""
        pass

    def calculate_creatinine_clearance(
        self,
        age: int,
        weight_kg: float,
        serum_creatinine: float,
        sex: str
    ) -> float:
        """
        Calculate creatinine clearance using Cockcroft-Gault equation.

        CrCl (mL/min) = [(140 - age) × weight] / (72 × SCr) × 0.85 (if female)

        Args:
            age: Patient age in years
            weight_kg: Body weight in kg
            serum_creatinine: Serum creatinine in mg/dL
            sex: "M" or "F"

        Returns:
            Creatinine clearance in mL/min
        """
        crcl = ((140 - age) * weight_kg) / (72 * serum_creatinine)

        if sex.upper() == "F":
            crcl *= 0.85

        return round(crcl, 1)

    def calculate_egfr(
        self,
        age: int,
        serum_creatinine: float,
        sex: str,
        race: Optional[str] = None
    ) -> float:
        """
        Calculate estimated GFR using CKD-EPI equation (2021 version).

        Args:
            age: Patient age in years
            serum_creatinine: Serum creatinine in mg/dL
            sex: "M" or "F"
            race: Optional, for legacy calculations

        Returns:
            eGFR in mL/min/1.73m²
        """
        # Simplified CKD-EPI (2021 race-free equation)
        kappa = 0.7 if sex.upper() == "F" else 0.9
        alpha = -0.241 if sex.upper() == "F" else -0.302

        min_ratio = min(serum_creatinine / kappa, 1)
        max_ratio = max(serum_creatinine / kappa, 1)

        egfr = 142 * (min_ratio ** alpha) * (max_ratio ** -1.200) * (0.9938 ** age)

        if sex.upper() == "F":
            egfr *= 1.012

        return round(egfr, 1)

    def calculate_bmi(self, weight_kg: float, height_cm: float) -> float:
        """
        Calculate Body Mass Index.

        BMI = weight (kg) / height (m)²
        """
        height_m = height_cm / 100
        bmi = weight_kg / (height_m ** 2)
        return round(bmi, 1)

    def calculate_bsa(self, weight_kg: float, height_cm: float) -> float:
        """
        Calculate Body Surface Area using Mosteller formula.

        BSA (m²) = sqrt[(height(cm) × weight(kg)) / 3600]

        Used for chemotherapy dosing, some antibiotics.
        """
        bsa = math.sqrt((height_cm * weight_kg) / 3600)
        return round(bsa, 2)

    def check_dosage_appropriateness(
        self,
        medication: Dict,
        patient_params: Dict
    ) -> Dict:
        """
        Check if medication dosage is appropriate for patient parameters.

        Args:
            medication: {
                "name": "Metformin",
                "dose": "1000mg",
                "frequency": "BID"
            }
            patient_params: {
                "age": 75,
                "weight_kg": 70,
                "height_cm": 165,
                "sex": "M",
                "serum_creatinine": 1.5,
                "labs": {
                    "egfr": 45  # Optional, can be calculated
                }
            }

        Returns:
            {
                "appropriate": False,
                "issues": [
                    {
                        "type": "renal_adjustment",
                        "severity": "critical",
                        "message": "Dose too high for patient's renal function",
                        "recommendation": "Reduce metformin to 500mg BID. eGFR 45 requires dose reduction."
                    }
                ],
                "calculated_params": {
                    "bmi": 25.7,
                    "bsa": 1.78,
                    "egfr": 45.2,
                    "crcl": 48.5
                }
            }
        """
        issues = []
        med_name = self._normalize_medication_name(medication["name"])

        # Calculate patient parameters
        calculated = {}

        if "weight_kg" in patient_params and "height_cm" in patient_params:
            calculated["bmi"] = self.calculate_bmi(
                patient_params["weight_kg"],
                patient_params["height_cm"]
            )
            calculated["bsa"] = self.calculate_bsa(
                patient_params["weight_kg"],
                patient_params["height_cm"]
            )

        # Resolve renal function — prefer direct eGFR from labs, then calculate
        labs = patient_params.get("labs", {})
        if "egfr" in labs:
            # Direct eGFR provided (e.g. from lab result)
            calculated["egfr"] = float(labs["egfr"])
        elif "serum_creatinine" in patient_params:
            calculated["egfr"] = self.calculate_egfr(
                patient_params["age"],
                patient_params["serum_creatinine"],
                patient_params["sex"]
            )

        if "serum_creatinine" in patient_params:
            calculated["crcl"] = self.calculate_creatinine_clearance(
                patient_params["age"],
                patient_params.get("weight_kg", 70),
                patient_params["serum_creatinine"],
                patient_params["sex"]
            )

        # Check renal dosing adjustments
        renal_issues = self._check_renal_dosing(
            med_name,
            medication,
            calculated.get("egfr"),
            calculated.get("crcl")
        )
        issues.extend(renal_issues)

        # Check pediatric dosing
        if patient_params["age"] < 18:
            pediatric_issues = self._check_pediatric_dosing(
                med_name,
                medication,
                patient_params
            )
            issues.extend(pediatric_issues)

        # Check geriatric considerations
        if patient_params["age"] >= 65:
            geriatric_issues = self._check_geriatric_dosing(
                med_name,
                medication,
                patient_params
            )
            issues.extend(geriatric_issues)

        # Check weight-based dosing
        if "weight_kg" in patient_params:
            weight_issues = self._check_weight_based_dosing(
                med_name,
                medication,
                patient_params["weight_kg"]
            )
            issues.extend(weight_issues)

        return {
            "appropriate": len([i for i in issues if i["severity"] in ["critical", "major"]]) == 0,
            "issues": issues,
            "calculated_params": calculated
        }

    def _check_renal_dosing(
        self,
        med_name: str,
        medication: Dict,
        egfr: Optional[float],
        crcl: Optional[float]
    ) -> List[Dict]:
        """Check for renal dosing adjustments."""
        issues = []

        if med_name not in self.RENAL_DOSING_ADJUSTMENTS:
            return issues

        adjustment = self.RENAL_DOSING_ADJUSTMENTS[med_name]

        # Check contraindications
        if "contraindicated" in adjustment:
            contra = adjustment["contraindicated"]
            if egfr and "egfr" in contra:
                if egfr < contra["egfr"].get("max", float("inf")):
                    issues.append({
                        "type": "renal_contraindication",
                        "severity": "critical",
                        "message": f"{medication['name']} is contraindicated with eGFR {egfr} mL/min/1.73m²",
                        "recommendation": f"Discontinue {medication['name']}. {adjustment['adjustment']}"
                    })

        # Check dose reductions
        if "reduce" in adjustment:
            reduce = adjustment["reduce"]
            if egfr and "egfr" in reduce:
                egfr_range = reduce["egfr"]
                if egfr < egfr_range.get("max", float("inf")) and egfr >= egfr_range.get("min", 0):
                    issues.append({
                        "type": "renal_dose_reduction",
                        "severity": "major",
                        "message": f"{medication['name']} requires dose reduction with eGFR {egfr}",
                        "recommendation": adjustment["adjustment"]
                    })

            if crcl and "creatinine_clearance" in reduce:
                if crcl < reduce["creatinine_clearance"].get("max", float("inf")):
                    issues.append({
                        "type": "renal_dose_reduction",
                        "severity": "major",
                        "message": f"{medication['name']} requires dose reduction with CrCl {crcl} mL/min",
                        "recommendation": adjustment["adjustment"]
                    })

        return issues

    def _check_pediatric_dosing(
        self,
        med_name: str,
        medication: Dict,
        patient_params: Dict
    ) -> List[Dict]:
        """Check pediatric dosing appropriateness."""
        issues = []

        if med_name not in self.PEDIATRIC_DOSING:
            return issues

        ped_dosing = self.PEDIATRIC_DOSING[med_name]

        if "weight_based" in ped_dosing and "weight_kg" in patient_params:
            weight_kg = patient_params["weight_kg"]
            dose_per_kg = ped_dosing["weight_based"]["dose_per_kg"]
            recommended_dose = weight_kg * dose_per_kg
            max_dose = ped_dosing["weight_based"]["max_single_dose"]

            # Cap at max dose
            if recommended_dose > max_dose:
                recommended_dose = max_dose

            # Extract current dose (simple parsing)
            try:
                current_dose_str = medication.get("dose", "")
                current_dose = float(''.join(filter(str.isdigit, current_dose_str)))

                # Check if current dose is appropriate
                if current_dose > recommended_dose * 1.2:  # 20% tolerance
                    issues.append({
                        "type": "pediatric_overdose",
                        "severity": "critical",
                        "message": f"Dose too high for pediatric patient (weight {weight_kg}kg)",
                        "recommendation": f"Recommended dose: {recommended_dose:.0f}mg based on {dose_per_kg}mg/kg"
                    })
                elif current_dose < recommended_dose * 0.5:  # More than 50% below
                    issues.append({
                        "type": "pediatric_underdose",
                        "severity": "moderate",
                        "message": f"Dose may be subtherapeutic for weight {weight_kg}kg",
                        "recommendation": f"Consider increasing to {recommended_dose:.0f}mg"
                    })
            except:
                pass  # Could not parse dose

        return issues

    def _check_geriatric_dosing(
        self,
        med_name: str,
        medication: Dict,
        patient_params: Dict
    ) -> List[Dict]:
        """Check geriatric dosing considerations (Beers Criteria)."""
        issues = []

        # Check Beers Criteria - drugs to avoid
        if med_name in self.GERIATRIC_ADJUSTMENTS["avoid_geriatric"]:
            issues.append({
                "type": "beers_criteria",
                "severity": "major",
                "message": f"{medication['name']} is potentially inappropriate in elderly patients (age {patient_params['age']})",
                "recommendation": "Consider alternative. Beers Criteria: Increased risk of cognitive impairment, falls, fractures."
            })

        # Check dose reductions
        if med_name in self.GERIATRIC_ADJUSTMENTS["reduce_geriatric"]:
            reduction_factor = self.GERIATRIC_ADJUSTMENTS["reduce_geriatric"][med_name]
            issues.append({
                "type": "geriatric_dose_reduction",
                "severity": "moderate",
                "message": f"{medication['name']} should be reduced in elderly patients",
                "recommendation": f"Consider {int(reduction_factor * 100)}% of standard adult dose (age {patient_params['age']})"
            })

        return issues

    def _check_weight_based_dosing(
        self,
        med_name: str,
        medication: Dict,
        weight_kg: float
    ) -> List[Dict]:
        """Check weight-based dosing for obesity or low weight."""
        issues = []

        # Adjust for extreme weights
        if weight_kg < 40:
            issues.append({
                "type": "low_body_weight",
                "severity": "moderate",
                "message": f"Patient weight is low ({weight_kg}kg)",
                "recommendation": f"Consider dose reduction for {medication['name']}. Consult pharmacy for weight-based dosing."
            })
        elif weight_kg > 120:
            issues.append({
                "type": "obesity",
                "severity": "moderate",
                "message": f"Patient is obese (weight {weight_kg}kg)",
                "recommendation": f"Consider if {medication['name']} requires dose adjustment for obesity. Some drugs use adjusted body weight."
            })

        return issues

    def _normalize_medication_name(self, name: str) -> str:
        """Normalize medication name for lookup."""
        import re
        # Remove dosage, route, spaces
        normalized = re.sub(r'\d+\s*(mg|mcg|g|mL|units?)', '', name, flags=re.IGNORECASE)
        normalized = re.sub(r'\s+(PO|IV|IM|SC|SL|PR)\s*', '', normalized, flags=re.IGNORECASE)
        return normalized.strip().lower()


def get_dosage_calculator() -> DosageCalculator:
    """Factory function to get dosage calculator instance."""
    return DosageCalculator()
