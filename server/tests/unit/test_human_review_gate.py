"""
Unit tests for human_review_gate.py
"""

import pytest
from app.agents.nodes.review_gate import (
    check_validation_issues,
    check_conflict_issues,
    check_state_flags,
    human_review_gate_node
)
from app.agents.state import GraphState


class TestCheckValidationIssues:
    """Tests for checking validation report issues."""

    def test_detect_schema_errors(self):
        """Test detection of schema errors."""
        report = {
            "schema_errors": [
                {"field": "medications[0].dose", "error": "Invalid format"}
            ],
            "missing_fields": [],
            "confidence": 0.9,
            "needs_review": False
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is True
        assert len(reasons) > 0
        assert any("schema" in r.lower() for r in reasons)

    def test_detect_missing_fields(self):
        """Test detection of missing required fields."""
        report = {
            "schema_errors": [],
            "missing_fields": ["allergies", "medications"],
            "confidence": 0.9,
            "needs_review": False
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is True
        assert any("missing" in r.lower() for r in reasons)

    def test_detect_low_confidence(self):
        """Test detection of low confidence scores."""
        report = {
            "schema_errors": [],
            "missing_fields": [],
            "confidence": 0.65,
            "needs_review": False
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is True
        assert any("confidence" in r.lower() for r in reasons)

    def test_detect_explicit_needs_review_flag(self):
        """Test detection of explicit needs_review flag."""
        report = {
            "schema_errors": [],
            "missing_fields": [],
            "confidence": 0.9,
            "needs_review": True
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is True
        assert any("flagged for review" in r.lower() for r in reasons)

    def test_clean_validation_report(self):
        """Test that clean report doesn't trigger review."""
        report = {
            "schema_errors": [],
            "missing_fields": [],
            "confidence": 0.92,
            "needs_review": False
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is False
        assert len(reasons) == 0

    def test_multiple_issues(self):
        """Test detection of multiple issues."""
        report = {
            "schema_errors": [{"field": "test", "error": "error"}],
            "missing_fields": ["field1", "field2"],
            "confidence": 0.6,
            "needs_review": True
        }

        needs_review, reasons = check_validation_issues(report)

        assert needs_review is True
        assert len(reasons) >= 4  # All issues should be detected

    def test_confidence_threshold(self):
        """Test confidence threshold boundary."""
        # Just above threshold - should pass
        report_ok = {
            "schema_errors": [],
            "missing_fields": [],
            "confidence": 0.71,
            "needs_review": False
        }

        needs_review, _ = check_validation_issues(report_ok)
        assert needs_review is False

        # Just below threshold - should fail
        report_low = {
            "schema_errors": [],
            "missing_fields": [],
            "confidence": 0.69,
            "needs_review": False
        }

        needs_review, _ = check_validation_issues(report_low)
        assert needs_review is True


class TestCheckConflictIssues:
    """Tests for checking conflict report issues."""

    def test_detect_unresolved_conflicts(self):
        """Test detection of unresolved conflicts."""
        report = {
            "conflicts": ["Conflict 1", "Conflict 2"],
            "unresolved": True
        }

        needs_review, reasons = check_conflict_issues(report)

        assert needs_review is True
        assert any("unresolved" in r.lower() for r in reasons)

    def test_detect_conflicts_list(self):
        """Test detection of conflicts in conflicts list."""
        report = {
            "conflicts": ["Blood pressure: 120/80 vs 140/90"],
            "unresolved": False
        }

        needs_review, reasons = check_conflict_issues(report)

        assert needs_review is True
        assert any("conflict" in r.lower() for r in reasons)

    def test_clean_conflict_report(self):
        """Test that clean conflict report doesn't trigger review."""
        report = {
            "conflicts": [],
            "unresolved": False
        }

        needs_review, reasons = check_conflict_issues(report)

        assert needs_review is False
        assert len(reasons) == 0

    def test_multiple_conflicts(self):
        """Test detection of multiple conflicts."""
        report = {
            "conflicts": ["Conflict 1", "Conflict 2", "Conflict 3"],
            "unresolved": True
        }

        needs_review, reasons = check_conflict_issues(report)

        assert needs_review is True
        # Should mention number of conflicts
        assert any("3" in r or "conflict" in r.lower() for r in reasons)


class TestCheckStateFlags:
    """Tests for checking state flags."""

    def test_detect_needs_review_flag(self):
        """Test detection of needs_review flag."""
        flags = {"needs_review": True}

        needs_review, reasons = check_state_flags(flags)

        assert needs_review is True
        assert any("flagged for review" in r.lower() for r in reasons)

    def test_detect_processing_error_flag(self):
        """Test detection of processing_error flag."""
        flags = {"processing_error": True}

        needs_review, reasons = check_state_flags(flags)

        assert needs_review is True
        assert any("error" in r.lower() for r in reasons)

    def test_detect_low_quality_flag(self):
        """Test detection of low_quality flag."""
        flags = {"low_quality": True}

        needs_review, reasons = check_state_flags(flags)

        assert needs_review is True
        assert any("quality" in r.lower() for r in reasons)

    def test_clean_flags(self):
        """Test that clean flags don't trigger review."""
        flags = {}

        needs_review, reasons = check_state_flags(flags)

        assert needs_review is False
        assert len(reasons) == 0

    def test_multiple_flags(self):
        """Test detection of multiple flags."""
        flags = {
            "needs_review": True,
            "processing_error": True,
            "low_quality": True
        }

        needs_review, reasons = check_state_flags(flags)

        assert needs_review is True
        assert len(reasons) == 3


@pytest.mark.unit
class TestHumanReviewGateNode:
    """Tests for the human_review_gate_node function."""

    def test_gate_triggers_on_validation_errors(
        self,
        minimal_graph_state,
        validation_report_with_errors
    ):
        """Test that gate triggers on validation errors."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_with_errors

        result = human_review_gate_node(state)

        assert result["flags"]["awaiting_human_review"] is True
        assert "review_reasons" in result["flags"]
        assert len(result["flags"]["review_reasons"]) > 0

    def test_gate_triggers_on_conflicts(
        self,
        minimal_graph_state,
        conflict_report_with_conflicts
    ):
        """Test that gate triggers on conflicts."""
        state = minimal_graph_state.copy()
        state["conflict_report"] = conflict_report_with_conflicts

        result = human_review_gate_node(state)

        assert result["flags"]["awaiting_human_review"] is True

    def test_gate_passes_clean_state(
        self,
        minimal_graph_state,
        validation_report_clean,
        conflict_report_clean
    ):
        """Test that gate passes with clean reports."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_clean
        state["conflict_report"] = conflict_report_clean

        result = human_review_gate_node(state)

        assert result["flags"].get("awaiting_human_review") is False

    def test_gate_updates_trace_log_when_paused(
        self,
        minimal_graph_state,
        validation_report_with_errors
    ):
        """Test that trace log is updated when paused for review."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_with_errors

        result = human_review_gate_node(state)

        # Check trace log
        assert len(result["controls"]["trace_log"]) > 0
        last_entry = result["controls"]["trace_log"][-1]
        assert last_entry["node"] == "human_review_gate"
        assert last_entry["action"] == "paused_for_review"
        assert "reasons" in last_entry

    def test_gate_updates_trace_log_when_approved(
        self,
        minimal_graph_state,
        validation_report_clean
    ):
        """Test that trace log is updated when automatically approved."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_clean

        result = human_review_gate_node(state)

        # Check trace log
        assert len(result["controls"]["trace_log"]) > 0
        last_entry = result["controls"]["trace_log"][-1]
        assert last_entry["action"] == "approved_automatically"

    def test_gate_sets_message_on_pause(
        self,
        minimal_graph_state,
        validation_report_with_errors
    ):
        """Test that message is set when paused for review."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_with_errors

        result = human_review_gate_node(state)

        assert result["message"] is not None
        assert "paused" in result["message"].lower()
        assert "review" in result["message"].lower()

    def test_gate_combines_multiple_issues(self, minimal_graph_state):
        """Test that gate combines issues from multiple sources."""
        state = minimal_graph_state.copy()
        state["validation_report"] = {
            "schema_errors": [{"field": "test", "error": "error"}],
            "missing_fields": [],
            "confidence": 0.9,
            "needs_review": False
        }
        state["conflict_report"] = {
            "conflicts": ["Conflict 1"],
            "unresolved": True
        }
        state["flags"] = {"low_quality": True}

        result = human_review_gate_node(state)

        # Should trigger review
        assert result["flags"]["awaiting_human_review"] is True
        # Should have reasons from all sources
        reasons = result["flags"]["review_reasons"]
        assert len(reasons) >= 3  # validation + conflict + flag

    def test_gate_handles_missing_reports(self, minimal_graph_state):
        """Test that gate handles missing validation/conflict reports."""
        state = minimal_graph_state.copy()
        # No validation_report or conflict_report

        result = human_review_gate_node(state)

        # Should not crash, should check flags only
        assert "awaiting_human_review" in result["flags"]

    def test_gate_handles_none_reports(self, minimal_graph_state):
        """Test that gate handles None reports."""
        state = minimal_graph_state.copy()
        state["validation_report"] = None
        state["conflict_report"] = None

        result = human_review_gate_node(state)

        # Should not crash
        assert "awaiting_human_review" in result["flags"]

    def test_gate_clears_previous_review_flag(
        self,
        minimal_graph_state,
        validation_report_clean
    ):
        """Test that gate clears previous review flag if state is clean."""
        state = minimal_graph_state.copy()
        state["flags"]["awaiting_human_review"] = True  # Previously set
        state["validation_report"] = validation_report_clean

        result = human_review_gate_node(state)

        assert result["flags"]["awaiting_human_review"] is False

    def test_gate_preserves_other_flags(
        self,
        minimal_graph_state,
        validation_report_with_errors
    ):
        """Test that gate preserves other flags in state."""
        state = minimal_graph_state.copy()
        state["flags"]["custom_flag"] = "custom_value"
        state["validation_report"] = validation_report_with_errors

        result = human_review_gate_node(state)

        # Custom flag should be preserved
        assert result["flags"]["custom_flag"] == "custom_value"

    def test_gate_review_reasons_include_details(
        self,
        minimal_graph_state,
        validation_report_with_errors
    ):
        """Test that review reasons include helpful details."""
        state = minimal_graph_state.copy()
        state["validation_report"] = validation_report_with_errors

        result = human_review_gate_node(state)

        reasons = result["flags"]["review_reasons"]
        # Should include specific information
        assert any("schema" in r.lower() or "error" in r.lower() for r in reasons)
