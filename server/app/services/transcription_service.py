"""
Transcription Service — orchestrates the LangGraph workflow for a request.

Provides a high-level API for running the full clinical transcription
pipeline (ingest → clean → … → package) without exposing LangGraph
internals to the API routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.state import GraphState, TranscriptSegment


class TranscriptionService:
    """
    Facade over the LangGraph clinical transcription workflow.

    Holds a compiled graph and provides request-level methods.
    """

    def __init__(self, app=None):
        """
        Args:
            app: A pre-compiled LangGraph application.
                 If None, ``build_graph()`` is called lazily on first use.
        """
        self._app = app

    @property
    def app(self):
        if self._app is None:
            from app.agents.graph import build_graph
            self._app = build_graph()
        return self._app

    def run_full_pipeline(
        self,
        session_id: str,
        patient_id: str,
        doctor_id: str,
        segments: List[TranscriptSegment],
        thread_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the entire transcription-to-record pipeline.

        Args:
            session_id:  Active session identifier.
            patient_id:  Patient being documented.
            doctor_id:   Authoring clinician.
            segments:    Raw transcript segments from speech recognition.
            thread_id:   Optional checkpoint thread (defaults to session_id).

        Returns:
            Final GraphState as a dict.
        """
        config = {
            "configurable": {
                "thread_id": thread_id or session_id,
            }
        }

        initial_state: GraphState = {
            "session_id": session_id,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "conversation_log": [],
            "new_segments": segments,
            "session_summary": None,
            "patient_record_fields": None,
            "message": None,
            "flags": {},
            "inputs": {},
            "documents": [],
            "chunks": [],
            "candidate_facts": [],
            "evidence_map": {},
            "structured_record": {},
            "validation_report": None,
            "conflict_report": None,
            "clinical_note": None,
            "clinical_suggestions": None,
            "controls": {
                "attempts": {},
                "budget": {"max_total_llm_calls": 30, "llm_calls_used": 0},
                "trace_log": [],
            },
        }

        return self.app.invoke(initial_state, config=config)

    def add_segments(
        self,
        thread_id: str,
        segments: List[TranscriptSegment],
    ) -> Dict[str, Any]:
        """
        Resume a checkpointed workflow with new transcript segments.

        Requires a checkpoint-enabled graph.
        """
        config = {"configurable": {"thread_id": thread_id}}
        update = {"new_segments": segments}
        return self.app.invoke(update, config=config)
