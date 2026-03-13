"""
External Drug Database Client

Integrates with external APIs for comprehensive drug information:
- RxNorm (NLM) - drug nomenclature and relationships
- OpenFDA - drug labels, adverse events
- DrugBank (optional) - comprehensive drug data

All APIs respect rate limits and include caching.
"""

import requests
from typing import Dict, List, Optional
import time
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class DrugDatabaseClient:
    """
    Client for external drug databases with fallback support.

    Uses free government APIs by default (RxNorm, OpenFDA).
    Can be extended to use commercial APIs (FDB, Lexicomp) in production.
    """

    # API Endpoints
    RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
    OPENFDA_BASE = "https://api.fda.gov/drug"
    DRUGBANK_BASE = "https://go.drugbank.com/api/v1"  # Requires API key

    # Rate limits (requests per hour)
    OPENFDA_RATE_LIMIT = 1000
    RXNORM_RATE_LIMIT = 20  # Conservative

    def __init__(
        self,
        drugbank_api_key: Optional[str] = None,
        enable_caching: bool = True
    ):
        """
        Initialize drug database client.

        Args:
            drugbank_api_key: Optional DrugBank API key for enhanced data
            enable_caching: Enable response caching (default: True)
        """
        self.drugbank_api_key = drugbank_api_key
        self.enable_caching = enable_caching

        # Rate limiting
        self._last_rxnorm_call = 0
        self._last_openfda_call = 0

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MedicalTranscriptionApp/1.0"
        })

    def _rate_limit(self, service: str):
        """Simple rate limiting."""
        now = time.time()

        if service == "rxnorm":
            min_interval = 3600 / self.RXNORM_RATE_LIMIT
            if now - self._last_rxnorm_call < min_interval:
                time.sleep(min_interval - (now - self._last_rxnorm_call))
            self._last_rxnorm_call = time.time()

        elif service == "openfda":
            min_interval = 3600 / self.OPENFDA_RATE_LIMIT
            if now - self._last_openfda_call < min_interval:
                time.sleep(min_interval - (now - self._last_openfda_call))
            self._last_openfda_call = time.time()

    @lru_cache(maxsize=1000)
    def get_drug_interactions(self, drug_name: str) -> List[Dict]:
        """
        Get drug-drug interactions from RxNorm.

        Args:
            drug_name: Drug name (e.g., "warfarin", "Aspirin")

        Returns:
            List of interactions with severity and description
        """
        try:
            # Step 1: Get RxCUI (RxNorm Concept Unique Identifier)
            rxcui = self._get_rxcui(drug_name)
            if not rxcui:
                logger.warning(f"Could not find RxCUI for {drug_name}")
                return []

            # Step 2: Get interactions
            self._rate_limit("rxnorm")
            url = f"{self.RXNORM_BASE}/interaction/interaction.json"
            params = {"rxcui": rxcui}

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            interactions = []
            if "interactionTypeGroup" in data:
                for type_group in data["interactionTypeGroup"]:
                    for interaction_type in type_group.get("interactionType", []):
                        for pair in interaction_type.get("interactionPair", []):
                            interactions.append({
                                "drug1": pair["interactionConcept"][0]["minConceptItem"]["name"],
                                "drug2": pair["interactionConcept"][1]["minConceptItem"]["name"],
                                "severity": pair.get("severity", "unknown"),
                                "description": pair.get("description", ""),
                                "source": "RxNorm"
                            })

            return interactions

        except Exception as e:
            logger.error(f"Error fetching interactions for {drug_name}: {e}")
            return []

    @lru_cache(maxsize=500)
    def _get_rxcui(self, drug_name: str) -> Optional[str]:
        """
        Get RxCUI for a drug name.

        Args:
            drug_name: Drug name

        Returns:
            RxCUI string or None
        """
        try:
            self._rate_limit("rxnorm")
            url = f"{self.RXNORM_BASE}/rxcui.json"
            params = {"name": drug_name}

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if "idGroup" in data and "rxnormId" in data["idGroup"]:
                return data["idGroup"]["rxnormId"][0]

            return None

        except Exception as e:
            logger.error(f"Error getting RxCUI for {drug_name}: {e}")
            return None

    @lru_cache(maxsize=500)
    def get_drug_label(self, drug_name: str) -> Optional[Dict]:
        """
        Get FDA drug label information from OpenFDA.

        Args:
            drug_name: Drug name (brand or generic)

        Returns:
            Drug label data including warnings, indications, dosing
        """
        try:
            self._rate_limit("openfda")
            url = f"{self.OPENFDA_BASE}/label.json"

            # Search by brand name or generic name
            search_query = f'openfda.brand_name:"{drug_name}" OR openfda.generic_name:"{drug_name}"'
            params = {
                "search": search_query,
                "limit": 1
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if "results" in data and len(data["results"]) > 0:
                result = data["results"][0]

                return {
                    "drug_name": drug_name,
                    "brand_names": result.get("openfda", {}).get("brand_name", []),
                    "generic_name": result.get("openfda", {}).get("generic_name", []),
                    "warnings": result.get("warnings", []),
                    "contraindications": result.get("contraindications", []),
                    "indications_and_usage": result.get("indications_and_usage", []),
                    "dosage_and_administration": result.get("dosage_and_administration", []),
                    "adverse_reactions": result.get("adverse_reactions", []),
                    "drug_interactions": result.get("drug_interactions", []),
                    "pregnancy": result.get("pregnancy", []),
                    "geriatric_use": result.get("geriatric_use", []),
                    "pediatric_use": result.get("pediatric_use", []),
                    "source": "OpenFDA"
                }

            return None

        except Exception as e:
            logger.error(f"Error fetching drug label for {drug_name}: {e}")
            return None

    @lru_cache(maxsize=500)
    def get_adverse_events(
        self,
        drug_name: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get reported adverse events from OpenFDA.

        Args:
            drug_name: Drug name
            limit: Number of events to return

        Returns:
            List of adverse events with patient info and reactions
        """
        try:
            self._rate_limit("openfda")
            url = f"{self.OPENFDA_BASE}/event.json"

            search_query = f'patient.drug.medicinalproduct:"{drug_name}"'
            params = {
                "search": search_query,
                "limit": limit
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            events = []
            if "results" in data:
                for result in data["results"]:
                    patient = result.get("patient", {})
                    reactions = [r.get("reactionmeddrapt") for r in patient.get("reaction", [])]

                    events.append({
                        "patient_age": patient.get("patientonsetage"),
                        "patient_sex": patient.get("patientsex"),
                        "reactions": reactions,
                        "serious": result.get("serious", 0) == 1,
                        "outcome": result.get("seriousnessother"),
                        "source": "OpenFDA FAERS"
                    })

            return events

        except Exception as e:
            logger.error(f"Error fetching adverse events for {drug_name}: {e}")
            return []

    def get_drug_class(self, drug_name: str) -> Optional[Dict]:
        """
        Get drug class information from RxNorm.

        Args:
            drug_name: Drug name

        Returns:
            Drug class information
        """
        try:
            rxcui = self._get_rxcui(drug_name)
            if not rxcui:
                return None

            self._rate_limit("rxnorm")
            url = f"{self.RXNORM_BASE}/rxclass/class/byRxcui.json"
            params = {
                "rxcui": rxcui,
                "relaSource": "ATC"  # Anatomical Therapeutic Chemical
            }

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            classes = []
            if "rxclassDrugInfoList" in data:
                for drug_info in data["rxclassDrugInfoList"].get("rxclassDrugInfo", []):
                    class_info = drug_info.get("rxclassMinConceptItem", {})
                    classes.append({
                        "class_id": class_info.get("classId"),
                        "class_name": class_info.get("className"),
                        "class_type": drug_info.get("rela")
                    })

            return {
                "drug_name": drug_name,
                "rxcui": rxcui,
                "classes": classes,
                "source": "RxNorm/ATC"
            }

        except Exception as e:
            logger.error(f"Error fetching drug class for {drug_name}: {e}")
            return None

    def get_drug_properties(self, drug_name: str) -> Optional[Dict]:
        """
        Get comprehensive drug properties from RxNorm.

        Args:
            drug_name: Drug name

        Returns:
            Drug properties including ingredients, strength, form
        """
        try:
            rxcui = self._get_rxcui(drug_name)
            if not rxcui:
                return None

            self._rate_limit("rxnorm")
            url = f"{self.RXNORM_BASE}/rxcui/{rxcui}/properties.json"

            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            if "properties" in data:
                props = data["properties"]
                return {
                    "rxcui": props.get("rxcui"),
                    "name": props.get("name"),
                    "synonym": props.get("synonym"),
                    "tty": props.get("tty"),  # Term type
                    "language": props.get("language"),
                    "suppress": props.get("suppress"),
                    "source": "RxNorm"
                }

            return None

        except Exception as e:
            logger.error(f"Error fetching drug properties for {drug_name}: {e}")
            return None

    def check_contraindications(
        self,
        drug_name: str,
        patient_conditions: List[str]
    ) -> List[Dict]:
        """
        Check for contraindications based on patient conditions.

        Args:
            drug_name: Drug name
            patient_conditions: List of patient conditions/diagnoses

        Returns:
            List of contraindications found
        """
        contraindications = []

        # Get drug label
        label = self.get_drug_label(drug_name)
        if not label:
            return contraindications

        # Parse contraindications from label
        contraindication_text = " ".join(label.get("contraindications", []))

        for condition in patient_conditions:
            if condition.lower() in contraindication_text.lower():
                contraindications.append({
                    "drug": drug_name,
                    "condition": condition,
                    "severity": "critical",
                    "text": contraindication_text[:500],  # Truncate
                    "source": "FDA Label"
                })

        return contraindications

    def get_dosing_information(self, drug_name: str) -> Optional[Dict]:
        """
        Get dosing information from FDA label.

        Args:
            drug_name: Drug name

        Returns:
            Dosing information
        """
        label = self.get_drug_label(drug_name)
        if not label:
            return None

        return {
            "drug_name": drug_name,
            "standard_dosing": label.get("dosage_and_administration", []),
            "pediatric": label.get("pediatric_use", []),
            "geriatric": label.get("geriatric_use", []),
            "renal_impairment": self._extract_renal_dosing(label),
            "hepatic_impairment": self._extract_hepatic_dosing(label),
            "source": "FDA Label"
        }

    def _extract_renal_dosing(self, label: Dict) -> Optional[str]:
        """Extract renal dosing from label text."""
        text = " ".join(label.get("dosage_and_administration", []))

        # Look for renal keywords
        if any(keyword in text.lower() for keyword in ["renal", "creatinine", "gfr", "kidney"]):
            # Find relevant sentences
            sentences = text.split(".")
            renal_sentences = [s for s in sentences if any(kw in s.lower() for kw in ["renal", "creatinine", "gfr"])]
            return ". ".join(renal_sentences[:3])  # First 3 relevant sentences

        return None

    def _extract_hepatic_dosing(self, label: Dict) -> Optional[str]:
        """Extract hepatic dosing from label text."""
        text = " ".join(label.get("dosage_and_administration", []))

        if any(keyword in text.lower() for keyword in ["hepatic", "liver", "cirrhosis"]):
            sentences = text.split(".")
            hepatic_sentences = [s for s in sentences if any(kw in s.lower() for kw in ["hepatic", "liver"])]
            return ". ".join(hepatic_sentences[:3])

        return None


# DrugBank client (requires API key)
class DrugBankClient:
    """
    Client for DrugBank API (commercial/academic license required).

    Provides comprehensive drug data including:
    - Drug-drug interactions
    - Drug properties and targets
    - Pharmacology
    - Clinical trial data
    """

    BASE_URL = "https://go.drugbank.com/api/v1"

    def __init__(self, api_key: str):
        """
        Initialize DrugBank client.

        Args:
            api_key: DrugBank API key
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        })

    def get_drug(self, drugbank_id: str) -> Optional[Dict]:
        """
        Get comprehensive drug data from DrugBank.

        Args:
            drugbank_id: DrugBank ID (e.g., "DB00945" for aspirin)

        Returns:
            Comprehensive drug data
        """
        try:
            url = f"{self.BASE_URL}/drugs/{drugbank_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching DrugBank data for {drugbank_id}: {e}")
            return None

    def search_drugs(self, query: str) -> List[Dict]:
        """
        Search DrugBank by drug name.

        Args:
            query: Drug name search query

        Returns:
            List of matching drugs
        """
        try:
            url = f"{self.BASE_URL}/drugs"
            params = {"q": query}

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            return response.json().get("results", [])

        except Exception as e:
            logger.error(f"Error searching DrugBank for {query}: {e}")
            return []


def get_drug_database_client(
    drugbank_api_key: Optional[str] = None
) -> DrugDatabaseClient:
    """Factory function to get drug database client."""
    return DrugDatabaseClient(drugbank_api_key=drugbank_api_key)
