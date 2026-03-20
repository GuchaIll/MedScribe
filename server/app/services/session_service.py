"""
Session Service — extracted from main.py.

Manages clinical transcription sessions: creation, transcript accumulation,
real-time agent analysis, and lifecycle management.

Two layers of persistence:
  1. In-memory store (fast, session-scoped, always active)
     – Holds the structured_record that gets updated incrementally
       whenever OCR processes a document or transcription yields clinical facts.
  2. DB-backed via SessionRepository (when db_session is provided)
     – Long-term storage: written only when the session ends. The entire
       consolidated structured_record is flushed to PostgreSQL as a
       MedicalRecord row.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.agents.tools.drug_checker import KNOWN_DRUGS

logger = logging.getLogger(__name__)


# ── Merge strategy constants ────────────────────────────────────────────────
# Which merge rule to apply for each top-level record section.

FIRST_WRITE = "first_write"      # Only populate if empty; flag conflict otherwise
DEDUP_APPEND = "dedup_append"    # Check for duplicate, then append
LATEST_WINS = "latest_wins"      # Unconditionally overwrite with incoming value

# Mapping of top-level (or dotted) record paths → strategy
_SECTION_STRATEGY: Dict[str, str] = {
    # First-write — demographics are identity fields
    "demographics":       FIRST_WRITE,
    "chief_complaint":    FIRST_WRITE,
    # Dedup + append — inherently multi-valued sections
    "hpi":                                    DEDUP_APPEND,
    "past_medical_history.chronic_conditions": DEDUP_APPEND,
    "past_medical_history.hospitalizations":   DEDUP_APPEND,
    "past_medical_history.surgeries":          DEDUP_APPEND,
    "past_medical_history.prior_diagnoses":    DEDUP_APPEND,
    "medications":        DEDUP_APPEND,
    "allergies":          DEDUP_APPEND,
    "family_history":     DEDUP_APPEND,
    "labs":               DEDUP_APPEND,
    "procedures":         DEDUP_APPEND,
    "diagnoses":          DEDUP_APPEND,
    "problem_list":       DEDUP_APPEND,
    "risk_factors":       DEDUP_APPEND,
    # Latest wins — these reflect the most recent state
    "vitals":             LATEST_WINS,
    "physical_exam":      LATEST_WINS,
    "social_history":     LATEST_WINS,
    "review_of_systems":  LATEST_WINS,
    "assessment":         LATEST_WINS,
    "plan":               LATEST_WINS,
    "visit":              LATEST_WINS,
}

# Dedup key used to identify "same item" in each list-type section.
# Keys **must** match what fill_record.py actually puts into each item dict.
_DEDUP_KEYS: Dict[str, str] = {
    "medications": "name",
    "allergies":   "substance",   # fill_record uses 'substance', not 'allergen'
    "labs":        "test",
    "procedures":  "name",
    "diagnoses":   "name",
    "problem_list": "name",       # fill_record uses 'name', not 'description'
    "risk_factors": "name",       # fill_record uses 'name', not 'factor'
    "hpi":         "symptom",     # fill_record uses 'symptom', not 'event'
    "family_history": "member",   # fill_record uses 'member', not 'relation'
    "past_medical_history.chronic_conditions": "name",
    "past_medical_history.hospitalizations":   "reason",
    "past_medical_history.surgeries":          "name",
    "past_medical_history.prior_diagnoses":    "name",
}


def _empty_record() -> Dict[str, Any]:
    """Return an empty mutable dict matching the StructuredRecord shape.

    Inlined from ``app.agents.nodes.record_schema.empty_record`` to avoid
    importing the full agent-nodes package (which triggers heavy ML deps).
    """
    return {
        "demographics": {
            "full_name": None, "date_of_birth": None, "age": None,
            "sex": None, "gender": None, "mrn": None,
            "contact_info": {"phone": None, "email": None, "address": None,
                             "city": None, "state": None, "zip": None},
            "insurance": {"provider": None, "policy_number": None,
                         "group_number": None, "subscriber_name": None},
            "emergency_contact": {"name": None, "relationship": None, "phone": None},
        },
        "visit": {"date": None, "type": None, "location": None, "provider": None},
        "chief_complaint": {"free_text": None, "onset": None, "duration": None,
                            "severity": None, "location": None},
        "hpi": [],
        "past_medical_history": {
            "chronic_conditions": [], "hospitalizations": [],
            "surgeries": [], "prior_diagnoses": [],
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
        "assessment": {"likely_diagnoses": [], "differential_diagnoses": [],
                      "clinical_reasoning": None},
        "plan": {
            "medications_prescribed": [], "tests_ordered": [],
            "lifestyle_recommendations": [], "follow_up": None, "referrals": [],
        },
        "_conflicts": [],
        "_low_confidence": [],
        "_db_seeded_fields": [],
    }


class SessionService:
    """
    Session store + clinical context pipeline.

    Modes:
      - In-memory: dict-backed (default, no persistence)
      - DB-backed: uses SessionRepository when db_session is set

    In production, pass ``db_session`` to enable persistence.
    """

    def __init__(self, db_session=None):
        # { session_id: { transcript, triggered_alerts, started_at } }
        self._store: Dict[str, Dict[str, Any]] = {}
        self._clinical_engine = None
        self._db_session = db_session
        self._session_repo = None
        self._patient_repo = None

        if db_session is not None:
            try:
                from app.database.repositories.session_repo import SessionRepository
                from app.database.repositories.patient_repo import PatientRepository
                self._session_repo = SessionRepository(db_session)
                self._patient_repo = PatientRepository(db_session)
            except Exception:
                pass

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start_session(self, patient_id: str = "", doctor_id: str = "") -> Dict[str, Any]:
        session_id = str(uuid.uuid4())

        # Lazy import that avoids triggering the heavy nodes __init__.py
        empty_record = _empty_record

        # In-memory store (always active for real-time analysis)
        self._store[session_id] = {
            "transcript": [],
            "triggered_alerts": set(),
            "started_at": datetime.now().isoformat(),
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "structured_record": empty_record(),   # session-level consolidated record
        }

        # Persist to DB if available
        if self._session_repo is not None and patient_id and doctor_id:
            try:
                from app.database.models import Session as DBSessionModel
                db_session = DBSessionModel(
                    id=session_id,
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    status="active",
                )
                self._session_repo.create(db_session)
                if self._db_session:
                    self._db_session.commit()
            except Exception as e:
                logger.warning("DB session creation failed: %s", e)

        return {"session_id": session_id, "message": "Session started"}

    def end_session(self, session_id: str) -> Dict[str, str]:
        session = self._store.get(session_id)

        # ── Flush consolidated record to PostgreSQL ─────────────────────
        if session and self._session_repo is not None:
            record = session.get("structured_record")
            if record:
                try:
                    self._persist_record_to_db(session_id, session, record)
                except Exception as e:
                    logger.warning("DB record flush on end_session failed: %s", e)

        self._store.pop(session_id, None)

        # Update DB session status if available
        if self._session_repo is not None:
            try:
                self._session_repo.end_session(session_id)
                if self._db_session:
                    self._db_session.commit()
            except Exception as e:
                logger.warning("DB session end failed: %s", e)

        return {"message": "Session ended"}

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get(session_id)

    # ── Structured Record (session-level) ───────────────────────────────────

    def get_structured_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return the session's in-memory consolidated structured record."""
        session = self._store.get(session_id)
        if session is None:
            return None
        return session.get("structured_record")

    def merge_structured_record(
        self,
        session_id: str,
        incoming: Dict[str, Any],
        source: str = "ocr",
    ) -> None:
        """
        Merge *incoming* partial record into the session's consolidated record.

        Three merge strategies are applied per-section:
          - FIRST_WRITE  → demographics, chief_complaint:
                only fill empty fields; flag conflicts if different values exist.
          - DEDUP_APPEND  → medications, allergies, labs, hpi, …:
                check for duplicates (case-insensitive key match), append new.
          - LATEST_WINS   → vitals, assessment, plan, social_history, …:
                unconditionally overwrite with the incoming value.

        All newly populated fields are tracked in ``_db_seeded_fields`` so the
        frontend can highlight them.
        """
        session = self._store.get(session_id)
        if session is None:
            logger.warning("merge_structured_record: session %s not found", session_id)
            return

        record = session.get("structured_record")
        if record is None:
            record = _empty_record()
            session["structured_record"] = record

        seeded: List[str] = record.setdefault("_db_seeded_fields", [])
        conflicts: List[Dict[str, Any]] = record.setdefault("_conflicts", [])
        low_conf: List[Dict[str, Any]] = record.setdefault("_low_confidence", [])

        for section_key, strategy in _SECTION_STRATEGY.items():
            # Resolve dotted paths (e.g. "past_medical_history.chronic_conditions")
            inc_val = _resolve_path(incoming, section_key)
            if inc_val is None:
                continue

            if strategy == DEDUP_APPEND:
                self._merge_dedup_append(record, section_key, inc_val, seeded, source)
            elif strategy == FIRST_WRITE:
                self._merge_first_write(record, section_key, inc_val, seeded, conflicts, source)
            elif strategy == LATEST_WINS:
                self._merge_latest_wins(record, section_key, inc_val, seeded, source)

        # Carry over _low_confidence from incoming if present
        for lc in (incoming.get("_low_confidence") or []):
            if lc not in low_conf:
                low_conf.append(lc)

        # Carry over _conflicts from incoming record (e.g. fill_record conflicts)
        for ic in (incoming.get("_conflicts") or []):
            # Avoid duplicate conflict entries
            if ic not in conflicts:
                conflicts.append(ic)

        logger.debug("Merged %s record into session %s (%d seeded fields, %d conflicts)",
                      source, session_id, len(seeded), len(conflicts))

    # ── Merge helpers (private) ─────────────────────────────────────────────

    @staticmethod
    def _merge_first_write(
        record: Dict, path: str, incoming: Any,
        seeded: List[str], conflicts: List[Dict], source: str,
    ) -> None:
        """Populate empty scalar/dict fields.  Flag conflict if value differs."""
        existing = _resolve_path(record, path)
        if existing is None:
            return
        if not isinstance(incoming, dict) or not isinstance(existing, dict):
            return
        for key, val in incoming.items():
            if key.startswith("_"):
                continue
            full_key = f"{path}.{key}"
            if isinstance(val, dict):
                # Recurse one level (e.g. demographics.contact_info)
                sub_existing = existing.setdefault(key, {})
                if isinstance(sub_existing, dict):
                    for sk, sv in val.items():
                        if sv is None or sv == "":
                            continue
                        sfull = f"{full_key}.{sk}"
                        cur = sub_existing.get(sk)
                        if cur is None or cur == "" or cur == "None":
                            sub_existing[sk] = sv
                            if sfull not in seeded:
                                seeded.append(sfull)
                        elif str(cur).lower().strip() != str(sv).lower().strip():
                            conflicts.append({
                                "field": sfull,
                                "db_value": str(cur),
                                "extracted_value": str(sv),
                                "confidence": 0.5,
                                "source": source,
                            })
            else:
                if val is None or val == "":
                    continue
                cur = existing.get(key)
                if cur is None or cur == "" or cur == "None":
                    existing[key] = val
                    if full_key not in seeded:
                        seeded.append(full_key)
                elif str(cur).lower().strip() != str(val).lower().strip():
                    conflicts.append({
                        "field": full_key,
                        "db_value": str(cur),
                        "extracted_value": str(val),
                        "confidence": 0.5,
                        "source": source,
                    })

    @staticmethod
    def _merge_dedup_append(
        record: Dict, path: str, incoming: Any,
        seeded: List[str], source: str,
    ) -> None:
        """Append list items that are not already present (case-insensitive dedup)."""
        target = _resolve_path(record, path)
        if target is None or not isinstance(target, list):
            return
        if not isinstance(incoming, list):
            return

        dedup_key = _DEDUP_KEYS.get(path, None)

        for item in incoming:
            if item is None:
                continue
            if isinstance(item, dict) and dedup_key:
                new_val = str(item.get(dedup_key, "")).lower().strip()
                if not new_val:
                    target.append(item)
                    continue
                already = any(
                    str(ex.get(dedup_key, "")).lower().strip() == new_val
                    for ex in target if isinstance(ex, dict)
                )
                if not already:
                    target.append(item)
                    if path not in seeded:
                        seeded.append(path)
            elif item not in target:
                target.append(item)
                if path not in seeded:
                    seeded.append(path)

    @staticmethod
    def _merge_latest_wins(
        record: Dict, path: str, incoming: Any,
        seeded: List[str], source: str,
    ) -> None:
        """Overwrite existing dict scalars with incoming values."""
        existing = _resolve_path(record, path)
        if existing is None:
            return
        if isinstance(incoming, dict) and isinstance(existing, dict):
            for key, val in incoming.items():
                if key.startswith("_"):
                    continue
                if val is None or val == "":
                    continue
                # For sub-lists in latest-wins sections (e.g. plan.medications_prescribed),
                # overwrite the entire list rather than appending.
                if isinstance(val, list):
                    if val:  # only overwrite if incoming is non-empty
                        existing[key] = val
                        full_key = f"{path}.{key}"
                        if full_key not in seeded:
                            seeded.append(full_key)
                else:
                    existing[key] = val
                    full_key = f"{path}.{key}"
                    if full_key not in seeded:
                        seeded.append(full_key)
        elif isinstance(incoming, list) and isinstance(existing, list):
            if incoming:
                existing.clear()
                existing.extend(incoming)
                if path not in seeded:
                    seeded.append(path)

    def _persist_record_to_db(
        self, session_id: str, session: Dict, record: Dict,
    ) -> None:
        """Flush the consolidated record to PostgreSQL as a MedicalRecord row."""
        try:
            from app.database.models import MedicalRecord
        except ImportError:
            logger.debug("MedicalRecord model not available; skipping DB persist")
            return

        patient_id = session.get("patient_id", "")
        doctor_id = session.get("doctor_id", "")

        # Strip internal metadata keys before persisting
        persist_data = {k: v for k, v in record.items() if not k.startswith("_")}

        try:
            db_record = MedicalRecord(
                id=str(uuid.uuid4()),
                patient_id=patient_id or "anonymous",
                session_id=session_id,
                structured_data=persist_data,
                clinical_suggestions=None,
                soap_note=None,
                validation_report=None,
                conflict_report=record.get("_conflicts"),
                confidence_score=None,
                version=1,
                is_final=False,
                record_type="session_consolidated",
                created_by=doctor_id or "system",
            )
            self._db_session.add(db_record)
            self._db_session.commit()
            logger.info("Persisted consolidated record for session %s", session_id)
        except Exception as e:
            logger.warning("Failed to persist record to DB: %s", e)
            try:
                self._db_session.rollback()
            except Exception:
                pass

    # ── Document & Queue Management ─────────────────────────────────────────

    def add_document(self, session_id: str, document_artifact: Dict[str, Any]) -> None:
        """Store an OCR-processed document artifact in the session."""
        session = self._store.get(session_id)
        if session is not None:
            session.setdefault("documents", []).append(document_artifact)

    def get_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """Return all document artifacts for a session."""
        session = self._store.get(session_id)
        if session is None:
            return []
        return session.get("documents", [])

    def add_to_queue(self, session_id: str, items: List[Dict[str, Any]]) -> None:
        """Add modification queue items to a session."""
        session = self._store.get(session_id)
        if session is not None:
            queue = session.setdefault("modification_queue", [])
            queue.extend(items)

    def get_queue(self, session_id: str) -> List[Dict[str, Any]]:
        """Return all modification queue items for a session."""
        session = self._store.get(session_id)
        if session is None:
            return []
        return session.get("modification_queue", [])

    def update_queue_item(
        self,
        session_id: str,
        item_id: str,
        status: str,
        corrected_value: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a single queue item's status and optional corrected value."""
        session = self._store.get(session_id)
        if session is None:
            return None

        queue = session.get("modification_queue", [])
        for item in queue:
            if item.get("item_id") == item_id:
                item["status"] = status
                if corrected_value is not None:
                    item["corrected_value"] = corrected_value
                return item

        return None

    # ── Transcription ───────────────────────────────────────────────────────

    def process_transcription(
        self,
        session_id: str,
        text: Optional[str],
        speaker: Optional[str] = "Unknown",
    ) -> Dict[str, Any]:
        """
        Append utterance, run clinical analysis after >= 2 turns.

        Returns:
            Response dict with session_id, speaker, transcription,
            source, and optional agent_message.
        """
        transcription = text or "[Audio received — Whisper transcription pending]"
        speaker = speaker or "Unknown"
        agent_message: Optional[str] = None

        session = self._store.get(session_id)
        if session is not None:
            session["transcript"].append({
                "speaker": speaker,
                "text": transcription,
                "timestamp": datetime.now().isoformat(),
            })

            if len(session["transcript"]) >= 2:
                try:
                    current_record, patient_history = self._extract_clinical_context(
                        session["transcript"]
                    )
                    if patient_history["found"]:
                        engine = self._get_clinical_engine()
                        suggestions = engine.generate_suggestions(
                            current_record=current_record,
                            patient_history=patient_history,
                        )
                        if suggestions.get("risk_level", "low") not in ("low",):
                            agent_message = self._format_agent_message(
                                suggestions, session["triggered_alerts"]
                            )

                    # ── Merge transcript-derived facts into the session record ──
                    self._merge_transcript_facts(
                        session_id, patient_history,
                    )
                except Exception as exc:
                    logger.warning("Clinical analysis error: %s", exc)

        return {
            "session_id": session_id,
            "speaker": speaker,
            "transcription": transcription,
            "source": "browser_speech_api" if text else "pending_whisper",
            "agent_message": agent_message,
        }

    # ── Internal helpers (moved from main.py) ───────────────────────────────

    def _get_clinical_engine(self):
        if self._clinical_engine is None:
            from app.core.clinical_suggestions import get_clinical_suggestion_engine
            self._clinical_engine = get_clinical_suggestion_engine()
        return self._clinical_engine

    def _merge_transcript_facts(
        self, session_id: str, patient_history: Dict[str, Any],
    ) -> None:
        """
        Convert clinical facts extracted from the transcript into a partial
        structured record and merge into the session's consolidated record.
        Runs inline — pure in-memory dict operations, sub-millisecond.
        """
        partial = _empty_record()
        had_data = False

        for med in patient_history.get("medications", []):
            name = med.get("name", "")
            if name:
                partial["medications"].append({
                    "name": name, "dose": "", "frequency": "", "route": "",
                    "source": "transcript", "confidence": 0.7,
                })
                had_data = True

        for allergy in patient_history.get("allergies", []):
            substance = allergy.get("substance", "")
            if substance:
                partial["allergies"].append({
                    "allergen": substance,
                    "reaction": allergy.get("reaction", ""),
                    "severity": allergy.get("severity", ""),
                    "source": "transcript", "confidence": 0.7,
                })
                had_data = True

        if had_data:
            self.merge_structured_record(session_id, partial, source="transcript")

    @staticmethod
    def _extract_clinical_context(transcript: List[Dict[str, str]]) -> tuple:
        """
        Scan accumulated transcript for drug names and allergy mentions.
        Returns (current_record, patient_history).
        """
        full_text = " ".join(t["text"] for t in transcript).lower()

        allergy_substances: Set[str] = set()
        allergies: List[Dict[str, str]] = []
        seen: Set[str] = set()
        stop_words = {"no", "any", "known", "the", "a", "drug", "food", "my", "have"}

        for pattern in [
            r"allergic to (\w+)",
            r"allergy to (\w+)",
            r"(\w+) allergy\b",
        ]:
            for match in re.finditer(pattern, full_text):
                substance = match.group(1)
                if substance not in stop_words and substance not in seen:
                    seen.add(substance)
                    allergy_substances.add(substance)
                    allergies.append({
                        "substance": substance,
                        "reaction": "reported by patient",
                        "severity": "unknown",
                    })

        medications = [
            {"name": drug}
            for drug in KNOWN_DRUGS
            if drug in full_text and drug not in allergy_substances
        ]

        current_record = {"medications": medications, "allergies": [], "diagnoses": []}
        patient_history = {
            "found": bool(medications or allergies),
            "allergies": allergies,
            "medications": medications,
            "diagnoses": [],
            "labs": [],
        }
        return current_record, patient_history

    @staticmethod
    def _format_agent_message(suggestions: dict, triggered: set) -> Optional[str]:
        """Convert new clinical alerts into a plain-text agent message."""
        new_parts: List[str] = []

        for alert in suggestions.get("allergy_alerts", []):
            key = f"allergy:{alert.get('allergen', '')}:{alert.get('medication', '')}"
            if key not in triggered:
                triggered.add(key)
                msg = alert.get("message") or (
                    f"{alert.get('medication', '?')} conflicts with "
                    f"{alert.get('allergen', '?')} allergy"
                )
                new_parts.append(f"\u26a0 Allergy Alert: {msg}")

        for interaction in suggestions.get("drug_interactions", []):
            d1, d2 = interaction.get("medication1", ""), interaction.get("medication2", "")
            key = "interaction:" + ":".join(sorted([d1, d2]))
            if key not in triggered:
                triggered.add(key)
                msg = interaction.get("message") or f"Interaction between {d1} and {d2}"
                sev = interaction.get("severity", "")
                new_parts.append(
                    f"\u26a0 Drug Interaction ({sev}): {msg}" if sev
                    else f"\u26a0 Drug Interaction: {msg}"
                )

        for contra in suggestions.get("contraindications", []):
            key = f"contra:{contra.get('medication', '')}:{contra.get('condition', '')}"
            if key not in triggered:
                triggered.add(key)
                msg = contra.get("message") or (
                    f"{contra.get('medication', '?')} contraindicated with "
                    f"{contra.get('condition', '?')}"
                )
                new_parts.append(f"\u26a0 Contraindication: {msg}")

        return ("Clinical AI: " + " | ".join(new_parts)) if new_parts else None


# ── Module-level helpers ────────────────────────────────────────────────────

def _resolve_path(d: Dict[str, Any], dotted_path: str) -> Any:
    """
    Navigate a nested dict using a dotted path like
    ``"past_medical_history.chronic_conditions"`` and return the value,
    or ``None`` if any intermediate key is missing.
    """
    parts = dotted_path.split(".")
    current: Any = d
    for p in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(p)
        if current is None:
            return None
    return current
