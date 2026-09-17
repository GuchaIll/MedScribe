"""
Unit tests for the parallel tool group runner (#51).

Plan §18.5: independent tools run in parallel, each with its own SQLAlchemy
session, and one failure never sinks the group.
"""

from __future__ import annotations

import threading

import pytest

from app.agents.tool_contracts import validate_tool_result
from app.agents.tools.registry import ToolOutcome, ToolRegistry, ToolScope
from app.agents.tools.runner import (
    MAX_GROUP_WORKERS,
    REFUSED_ERROR,
    ToolRequest,
    run_parallel_group,
)


def citation():
    return {
        "source_kind": "prior_docs",
        "source_id": "chunk:doc_1:p1:c1",
        "snippet": None,
        "observed_at": None,
        "received_at": "2026-09-16T09:00:00Z",
        "evidence_state": "materialized",
        "locator": {"page": 1, "char_start": 0, "char_end": 1},
        "score": None,
    }


@pytest.fixture
def registry():
    return ToolRegistry(ToolScope(session_id="ses_1", patient_id="pat_1"))


def assist(tool_id, args=None):
    return ToolRequest(tool_id=tool_id, args=args or {}, caller="fixed_executor", caller_ref="wf")


class TestGroupExecution:
    def test_empty_group_returns_nothing(self, registry):
        assert run_parallel_group(registry, []) == []

    def test_results_come_back_in_request_order(self, registry):
        def handler(call):
            return ToolOutcome(ok=True, data={"tool": call.tool_id}, citations=[citation()])

        for tool_id in ("retrieve_docs", "retrieve_visits", "retrieve_session"):
            registry.register(tool_id, handler)

        results = run_parallel_group(registry, [
            assist("retrieve_docs"), assist("retrieve_visits"), assist("retrieve_session"),
        ])
        assert [r["tool_id"] for r in results] == [
            "retrieve_docs", "retrieve_visits", "retrieve_session",
        ]

    def test_calls_actually_run_concurrently(self, registry):
        barrier = threading.Barrier(3, timeout=5)

        def handler(call):
            barrier.wait()  # times out and raises unless all three run at once
            return ToolOutcome(ok=True, data={}, citations=[citation()])

        for tool_id in ("retrieve_docs", "retrieve_visits", "retrieve_session"):
            registry.register(tool_id, handler)

        results = run_parallel_group(registry, [
            assist("retrieve_docs"), assist("retrieve_visits"), assist("retrieve_session"),
        ])
        assert all(result["ok"] for result in results)

    def test_trace_log_entries_follow_request_order(self, registry):
        def handler(call):
            return ToolOutcome(ok=True, data={}, citations=[citation()])

        for tool_id in ("retrieve_docs", "retrieve_visits"):
            registry.register(tool_id, handler)

        trace_log = []
        run_parallel_group(
            registry, [assist("retrieve_docs"), assist("retrieve_visits")], trace_log=trace_log,
        )
        assert [entry["tool_id"] for entry in trace_log] == ["retrieve_docs", "retrieve_visits"]

    def test_rejects_non_request_members(self, registry):
        with pytest.raises(TypeError):
            run_parallel_group(registry, [{"tool_id": "retrieve_docs"}])

    def test_rejects_zero_workers(self, registry):
        registry.register("retrieve_docs", lambda call: ToolOutcome(ok=True, citations=[citation()]))
        with pytest.raises(ValueError, match="max_workers"):
            run_parallel_group(registry, [assist("retrieve_docs")], max_workers=0)

    def test_worker_cap_matches_the_plan_budget(self):
        assert MAX_GROUP_WORKERS == 6


class TestFailureIsolation:
    def test_a_refused_call_does_not_sink_the_group(self, registry):
        registry.register("retrieve_docs", lambda call: ToolOutcome(ok=True, citations=[citation()]))
        # check_dosage is not registered here, so the registry refuses it.
        results = run_parallel_group(registry, [
            assist("retrieve_docs"),
            ToolRequest("check_dosage", {}, caller="planning_agent", caller_ref="plan_1"),
        ])
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert results[1]["error"] == REFUSED_ERROR
        assert "not registered" in results[1]["data"]["refusal_reason"]

    def test_refusal_result_is_contract_valid(self, registry):
        results = run_parallel_group(registry, [assist("retrieve_docs")])
        assert validate_tool_result(dict(results[0])) == []
        assert results[0]["receipt"]["session_id"] == "ses_1"

    def test_a_failing_handler_does_not_sink_the_group(self, registry):
        def boom(call):
            raise RuntimeError("backend down")

        registry.register("retrieve_docs", lambda call: ToolOutcome(ok=True, citations=[citation()]))
        registry.register("retrieve_visits", boom)
        results = run_parallel_group(registry, [assist("retrieve_docs"), assist("retrieve_visits")])
        assert [result["ok"] for result in results] == [True, False]


class TestSessionsPerCall:
    def test_each_call_gets_its_own_session(self, registry):
        sessions = []
        closed = []

        class Session:
            def close(self):
                closed.append(self)

        def factory():
            session = Session()
            sessions.append(session)
            return session

        seen = []

        def handler(call):
            seen.append(call.db)
            return ToolOutcome(ok=True, citations=[citation()])

        registry.register("retrieve_docs", handler)
        registry.register("retrieve_visits", handler)
        run_parallel_group(
            registry,
            [assist("retrieve_docs"), assist("retrieve_visits")],
            db_session_factory=factory,
        )
        assert len(sessions) == 2
        assert len(set(id(session) for session in seen)) == 2
        assert len(closed) == 2

    def test_a_failing_session_factory_still_runs_the_call(self, registry):
        def factory():
            raise RuntimeError("pool exhausted")

        registry.register("retrieve_docs", lambda call: ToolOutcome(ok=True, citations=[citation()]))
        results = run_parallel_group(
            registry, [assist("retrieve_docs")], db_session_factory=factory,
        )
        assert results[0]["ok"] is True
