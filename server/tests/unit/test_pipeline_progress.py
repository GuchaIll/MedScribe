import pytest

from app.core.pipeline_progress import PIPELINE_NODE_DEFS, PipelineProgressStore


@pytest.mark.unit
class TestPipelineProgressStore:
    @pytest.fixture
    def store(self):
        return PipelineProgressStore()

    def test_init_pipeline_starts_first_node(self, store):
        progress = store.init_pipeline("session-1")

        assert progress.session_id == "session-1"
        assert progress.status == "running"
        assert progress.current_node == PIPELINE_NODE_DEFS[0][0]
        assert progress.started_at is not None
        assert len(progress.nodes) == len(PIPELINE_NODE_DEFS)
        assert progress.nodes[0].status == "running"
        assert all(node.status == "pending" for node in progress.nodes[1:])

    def test_mark_node_completed_records_detail_and_starts_predicted_next(
        self, store, monkeypatch
    ):
        times = iter([100.0, 101.234, 102.0])
        monkeypatch.setattr("app.core.pipeline_progress.time.monotonic", lambda: next(times))

        store.init_pipeline("session-1")
        store.mark_node_completed("session-1", "greeting", detail="Loaded context")
        progress = store.get("session-1")

        greeting = next(node for node in progress.nodes if node.name == "greeting")
        next_node = next(
            node for node in progress.nodes if node.name == "load_patient_context"
        )

        assert greeting.status == "completed"
        assert greeting.detail == "Loaded context"
        assert greeting.completed_at is not None
        assert greeting.duration_ms == 1234.0
        assert next_node.status == "running"
        assert next_node.started_at is not None
        assert progress.current_node == "load_patient_context"

    def test_repair_completion_uses_custom_predicted_next(self, store):
        store.init_pipeline("session-1")
        store.mark_node_running("session-1", "repair")
        store.mark_node_completed("session-1", "repair")
        progress = store.get("session-1")

        validate_node = next(
            node for node in progress.nodes if node.name == "validate_and_score"
        )

        assert validate_node.status == "running"
        assert progress.current_node == "validate_and_score"

    def test_mark_node_skipped_only_changes_pending_nodes(self, store):
        store.init_pipeline("session-1")
        store.mark_node_skipped("session-1", "load_patient_context")
        store.mark_node_skipped("session-1", "greeting")
        progress = store.get("session-1")

        skipped = next(node for node in progress.nodes if node.name == "load_patient_context")
        running = next(node for node in progress.nodes if node.name == "greeting")

        assert skipped.status == "skipped"
        assert running.status == "running"

    def test_mark_pipeline_completed_marks_remaining_nodes_skipped(self, store):
        store.init_pipeline("session-1")
        store.mark_node_completed("session-1", "greeting")
        store.mark_pipeline_completed("session-1")
        progress = store.get("session-1")

        greeting = next(node for node in progress.nodes if node.name == "greeting")
        next_node = next(
            node for node in progress.nodes if node.name == "load_patient_context"
        )

        assert progress.status == "completed"
        assert progress.current_node is None
        assert progress.completed_at is not None
        assert greeting.status == "completed"
        assert next_node.status == "skipped"

    def test_mark_pipeline_failed_marks_running_node_failed_and_truncates_error(self, store):
        store.init_pipeline("session-1")
        error = "x" * 140

        store.mark_pipeline_failed("session-1", error)
        progress = store.get("session-1")
        running = next(node for node in progress.nodes if node.name == "greeting")

        assert progress.status == "failed"
        assert progress.error == error
        assert progress.completed_at is not None
        assert running.status == "failed"
        assert running.detail == error[:120]

    def test_get_dict_and_clear_round_trip(self, store):
        store.init_pipeline("session-1")

        progress_dict = store.get_dict("session-1")
        store.clear("session-1")

        assert progress_dict["session_id"] == "session-1"
        assert progress_dict["nodes"][0]["name"] == "greeting"
        assert store.get("session-1") is None
        assert store.get_dict("session-1") is None

    def test_unknown_session_operations_are_noops(self, store):
        store.mark_node_running("missing", "greeting")
        store.mark_node_completed("missing", "greeting")
        store.mark_node_skipped("missing", "greeting")
        store.mark_pipeline_completed("missing")
        store.mark_pipeline_failed("missing", "boom")

        assert store.get("missing") is None
