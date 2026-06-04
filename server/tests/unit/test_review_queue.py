"""
Unit tests for the physician review gate + Redis review queue.

Validates the P1 guarantee: when a pipeline run needs physician review, the
durable patient record is NOT mutated — the proposed record + discrepancies
are staged for end-of-session sign-off instead.

Covers:
  - build_discrepancies flattens validation + conflict reports
  - ReviewQueueStore stage/get/clear (in-memory fallback path)
  - persist_results_node stages (and does NOT call the record repo) when
    flags['awaiting_human_review'] is set
  - persist_results_node still persists on a clean/auto-approved run
"""

import pytest
from unittest.mock import MagicMock

from app.core.review_queue import (
    build_discrepancies,
    ReviewQueueStore,
)


# ── build_discrepancies ──────────────────────────────────────────────────────

class TestBuildDiscrepancies:
    def test_flattens_validation_and_conflict_reports(self):
        validation = {
            "schema_errors": ["medications[0].dose: invalid format"],
            "missing_fields": ["allergies"],
            "conflicts": [],
            "confidence": 0.62,
            "needs_review": True,
        }
        conflict = {"conflicts": ["BP: 120/80 vs 140/90"], "unresolved": True}

        discrepancies = build_discrepancies(validation, conflict)

        kinds = {d["kind"] for d in discrepancies}
        assert "schema_error" in kinds
        assert "missing_field" in kinds
        assert "low_confidence" in kinds       # confidence 0.62 < 0.7
        assert "conflict" in kinds             # from conflict report
        # Every row is reviewable and starts pending with a unique id.
        assert all(d["status"] == "pending" for d in discrepancies)
        assert len({d["id"] for d in discrepancies}) == len(discrepancies)

    def test_missing_field_carries_field_name(self):
        discrepancies = build_discrepancies(
            {"schema_errors": [], "missing_fields": ["dob"], "conflicts": []},
            None,
        )
        missing = [d for d in discrepancies if d["kind"] == "missing_field"]
        assert missing and missing[0]["field"] == "dob"

    def test_clean_reports_yield_no_discrepancies(self):
        clean = {"schema_errors": [], "missing_fields": [], "conflicts": [],
                 "confidence": 0.95, "needs_review": False}
        assert build_discrepancies(clean, {"conflicts": [], "unresolved": False}) == []

    def test_handles_none_reports(self):
        assert build_discrepancies(None, None) == []


# ── ReviewQueueStore (in-memory fallback) ─────────────────────────────────────

class TestReviewQueueStore:
    def _store(self):
        # No REDIS_URL in test env -> in-memory fallback.
        return ReviewQueueStore()

    def test_stage_and_get_roundtrip(self):
        store = self._store()
        payload = store.stage_pending_review(
            "S001",
            patient_id="P001",
            doctor_id="D001",
            proposed_record={"medications": [{"name": "Aspirin"}]},
            discrepancies=[{"id": "x", "kind": "conflict", "status": "pending"}],
            confidence_score=70.0,
        )
        assert payload["status"] == "pending_review"

        loaded = store.get("S001")
        assert loaded is not None
        assert loaded["patient_id"] == "P001"
        assert loaded["discrepancy_count"] == 1
        assert loaded["proposed_record"]["medications"][0]["name"] == "Aspirin"

    def test_clear_removes_entry(self):
        store = self._store()
        store.stage_pending_review(
            "S002", patient_id="P", doctor_id="D",
            proposed_record={}, discrepancies=[],
        )
        assert store.get("S002") is not None
        store.clear("S002")
        assert store.get("S002") is None


# ── persist_results_node review gate ──────────────────────────────────────────

@pytest.mark.unit
class TestPersistResultsReviewGate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.record_repo = MagicMock()
        ctx.embedding_service = MagicMock()
        ctx.session_repo = MagicMock()
        ctx.db_session_factory = MagicMock()
        ctx.grounding_threshold = 0.65
        ctx.persistence_floor = 0.60
        return ctx

    def _state(self, awaiting_review: bool):
        return {
            "session_id": "S001",
            "patient_id": "P001",
            "doctor_id": "D001",
            "structured_record": {"medications": [{"name": "Aspirin", "dose": "81mg"}]},
            "candidate_facts": [],
            "evidence_map": {},
            "clinical_note": None,
            "clinical_suggestions": None,
            "validation_report": {
                "schema_errors": [],
                "missing_fields": ["allergies"],
                "conflicts": [],
                "needs_review": True,
                "confidence": 0.6,
            },
            "conflict_report": {"conflicts": ["dose mismatch"], "unresolved": True},
            "flags": {"awaiting_human_review": awaiting_review},
            "controls": {"attempts": {}, "budget": {}, "trace_log": []},
            "message": "",
        }

    def test_review_path_stages_and_does_not_persist(self):
        """When review is needed, the durable record repo must NOT be touched."""
        from app.agents.nodes.persist_results import persist_results_node
        from app.core.review_queue import review_queue_store

        ctx = self._make_ctx()
        state = self._state(awaiting_review=True)

        result = persist_results_node(state, ctx)

        # No durable mutation.
        ctx.record_repo.create.assert_not_called()
        ctx.session_repo.end_session.assert_not_called()

        # Staged for review instead.
        staged = review_queue_store.get("S001")
        assert staged is not None
        assert staged["status"] == "pending_review"
        assert staged["discrepancy_count"] >= 2  # missing_field + conflict(s) + low_confidence

        # Trace records the staging decision.
        trace = result["controls"]["trace_log"]
        assert any(e.get("action") == "staged_for_review" for e in trace)

        review_queue_store.clear("S001")

    def test_clean_path_still_persists(self):
        """A clean/auto-approved run should persist durably as before."""
        from app.agents.nodes.persist_results import persist_results_node

        ctx = self._make_ctx()
        state = self._state(awaiting_review=False)
        # Clean reports so the non-gated path runs end-to-end.
        state["validation_report"] = {
            "schema_errors": [], "missing_fields": [], "conflicts": [],
            "needs_review": False, "confidence": 0.95,
        }
        state["conflict_report"] = None

        persist_results_node(state, ctx)

        # Durable persistence attempted (record repo received a create call).
        ctx.record_repo.create.assert_called_once()
