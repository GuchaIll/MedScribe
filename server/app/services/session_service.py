"""
Session Service — extracted from main.py.

Manages clinical transcription sessions: creation, transcript accumulation,
real-time agent analysis, and lifecycle management.

Supports two modes:
  1. In-memory store (default, for dev/testing)
  2. DB-backed via SessionRepository (when db_session is provided)
"""

from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.agents.tools.drug_checker import KNOWN_DRUGS

logger = logging.getLogger(__name__)


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

        # In-memory store (always active for real-time analysis)
        self._store[session_id] = {
            "transcript": [],
            "triggered_alerts": set(),
            "started_at": datetime.now().isoformat(),
            "patient_id": patient_id,
            "doctor_id": doctor_id,
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
        self._store.pop(session_id, None)

        # Update DB if available
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
