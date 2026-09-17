"""
Unit tests for LLM adapters, BudgetAwareLLMAdapter, and role config (#52).

All tests run without network calls (StubAdapter or mocks).

Coverage:
  - LLMAdapter protocol compliance via StubAdapter
  - BudgetAwareLLMAdapter: call capping, budget sharing across methods
  - LLMTool backward-compat alias
  - Per-role config loader: env-var parsing, fallback logging, bad format
  - ToolCallProposal construction and validation
  - Greeting feature flag: pipeline_progress.py + graph.py node list
"""

from __future__ import annotations

import os
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.agents.guardrails.budget import BudgetGuardrail
from app.agents.tools.llm import BudgetAwareLLMAdapter, LLMTool
from app.models.adapters.stub import StubAdapter
from app.models.llm import (
    BudgetExhaustedError,
    LLMConfigError,
    ToolCallProposal,
    _parse_role_env,
    load_adapter_for_role,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _SimpleModel(BaseModel):
    value: str
    count: int = 0


def _stub(responses=None, role="synthesis") -> StubAdapter:
    return StubAdapter(responses=responses or [], role=role)


# ---------------------------------------------------------------------------
# ToolCallProposal
# ---------------------------------------------------------------------------


class TestToolCallProposal:
    def test_basic_construction(self):
        p = ToolCallProposal(tool_name="get_labs", tool_args={"x": 1}, tool_call_id="abc")
        assert p.tool_name == "get_labs"
        assert p.tool_args == {"x": 1}
        assert p.tool_call_id == "abc"

    def test_empty_tool_name_raises(self):
        with pytest.raises(LLMConfigError, match="tool_name must be a non-empty string"):
            ToolCallProposal(tool_name="", tool_args={}, tool_call_id="x")

    def test_repr(self):
        p = ToolCallProposal(tool_name="foo", tool_args={}, tool_call_id="bar")
        assert "foo" in repr(p)
        assert "bar" in repr(p)


# ---------------------------------------------------------------------------
# StubAdapter — protocol compliance
# ---------------------------------------------------------------------------


class TestStubAdapterProtocol:
    def test_properties(self):
        s = _stub(role="router")
        assert s.provider == "stub"
        assert s.model == "stub"
        assert s.role == "router"

    def test_generate_returns_str(self):
        s = _stub(["hello world"])
        result = s.generate([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_generate_dict_response_serialized(self):
        s = _stub([{"answer": 42}])
        result = s.generate([{"role": "user", "content": "x"}])
        assert '"answer"' in result

    def test_generate_structured(self):
        s = _stub([{"value": "abc", "count": 7}])
        result = s.generate_structured([{"role": "user", "content": "x"}], _SimpleModel)
        assert isinstance(result, _SimpleModel)
        assert result.value == "abc"
        assert result.count == 7

    def test_generate_structured_invalid_raises(self):
        s = _stub([{"wrong_field": "x"}])
        with pytest.raises(ValueError, match="does not validate"):
            s.generate_structured([{"role": "user", "content": "x"}], _SimpleModel)

    def test_generate_with_tools_text(self):
        s = _stub(["no tool needed"])
        result = s.generate_with_tools(
            [{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "f"}}],
        )
        assert result == "no tool needed"

    def test_generate_with_tools_proposals(self):
        scripted_calls = [{"tool_name": "get_labs", "tool_args": {"patient": "p1"}}]
        s = _stub([scripted_calls])
        result = s.generate_with_tools(
            [{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "get_labs"}}],
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ToolCallProposal)
        assert result[0].tool_name == "get_labs"
        assert result[0].tool_args == {"patient": "p1"}

    def test_exhausted_raises(self):
        s = _stub([])
        with pytest.raises(StubAdapter.Exhausted, match="no scripted response"):
            s.generate([{"role": "user", "content": "x"}])

    def test_call_count_tracked(self):
        s = _stub(["a", "b"])
        s.generate([{"role": "user", "content": "x"}])
        s.generate([{"role": "user", "content": "y"}])
        assert s.call_count == 2

    def test_empty_messages_raises(self):
        s = _stub(["x"])
        with pytest.raises(ValueError, match="messages must be a non-empty list"):
            s.generate([])

    def test_add_response(self):
        s = _stub()
        s.add_response("hello")
        assert s.generate([{"role": "user", "content": "x"}]) == "hello"


# ---------------------------------------------------------------------------
# BudgetAwareLLMAdapter
# ---------------------------------------------------------------------------


class TestBudgetAwareLLMAdapter:
    def test_delegates_generate(self):
        adapter = _stub(["result"])
        budget = BudgetGuardrail(max_calls=10)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        assert bw.generate([{"role": "user", "content": "x"}]) == "result"

    def test_increments_budget_after_call(self):
        adapter = _stub(["r"])
        budget = BudgetGuardrail(max_calls=5, calls_used=0)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        bw.generate([{"role": "user", "content": "x"}])
        assert budget.calls_used == 1

    def test_budget_shared_across_methods(self):
        adapter = _stub(["text", {"value": "v"}, "text2"])
        budget = BudgetGuardrail(max_calls=3, calls_used=0)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        bw.generate([{"role": "user", "content": "x"}])
        bw.generate_structured([{"role": "user", "content": "x"}], _SimpleModel)
        bw.generate([{"role": "user", "content": "x"}])
        assert budget.calls_used == 3

    def test_budget_exhausted_before_call(self):
        adapter = _stub(["r"])
        budget = BudgetGuardrail(max_calls=0)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        with pytest.raises(BudgetExhaustedError, match="budget exhausted"):
            bw.generate([{"role": "user", "content": "x"}])

    def test_budget_exhausted_does_not_call_adapter(self):
        adapter = _stub()  # no scripted responses
        budget = BudgetGuardrail(max_calls=0)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        with pytest.raises(BudgetExhaustedError):
            bw.generate([{"role": "user", "content": "x"}])
        # Adapter should never have been called
        assert adapter.call_count == 0

    def test_none_adapter_raises(self):
        with pytest.raises(ValueError, match="adapter must not be None"):
            BudgetAwareLLMAdapter(None)  # type: ignore[arg-type]

    def test_default_budget_30_calls(self):
        adapter = _stub()
        bw = BudgetAwareLLMAdapter(adapter)
        assert bw.budget.max_calls == 30

    def test_forwarded_properties(self):
        adapter = _stub(role="planner")
        bw = BudgetAwareLLMAdapter(adapter)
        assert bw.provider == "stub"
        assert bw.model == "stub"
        assert bw.role == "planner"

    def test_generate_response_shim(self):
        adapter = _stub(["shim result"])
        bw = BudgetAwareLLMAdapter(adapter)
        result = bw.generate_response("hello")
        assert result == "shim result"
        assert bw.budget.calls_used == 1

    def test_generate_with_tools_budget(self):
        scripted = [{"tool_name": "x", "tool_args": {}}]
        adapter = _stub([scripted])
        budget = BudgetGuardrail(max_calls=2)
        bw = BudgetAwareLLMAdapter(adapter, budget)
        bw.generate_with_tools(
            [{"role": "user", "content": "y"}],
            tools=[{"type": "function", "function": {"name": "x"}}],
        )
        assert budget.calls_used == 1


# ---------------------------------------------------------------------------
# LLMTool backward-compat alias
# ---------------------------------------------------------------------------


class TestLLMToolBackwardCompat:
    def test_is_subclass(self):
        assert issubclass(LLMTool, BudgetAwareLLMAdapter)

    def test_max_calls_param(self):
        tool = LLMTool(max_calls=15)
        assert tool.max_calls == 15
        assert tool.budget.max_calls == 15

    def test_calls_used_property(self):
        tool = LLMTool(max_calls=5)
        assert tool.calls_used == 0
        assert tool.budget_remaining == 5
        assert not tool.exhausted

    def test_factory_param(self):
        mock_client = MagicMock()
        mock_client.generate_response.return_value = "from_factory"
        tool = LLMTool(factory=lambda: mock_client, max_calls=5)
        result = tool.generate([{"role": "user", "content": "hi"}])
        assert result == "from_factory"


# ---------------------------------------------------------------------------
# Per-role config: _parse_role_env
# ---------------------------------------------------------------------------


class TestParseRoleEnv:
    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_ROLE_ROUTER", None)
            assert _parse_role_env("router") is None

    def test_parses_valid_format(self):
        with patch.dict(os.environ, {"LLM_ROLE_ROUTER": "groq:openai/gpt-oss-20b"}):
            result = _parse_role_env("router")
        assert result == ("groq", "openai/gpt-oss-20b")

    def test_case_insensitive_role(self):
        with patch.dict(os.environ, {"LLM_ROLE_SYNTHESIS": "anthropic:claude-haiku-4-5-20251001"}):
            result = _parse_role_env("synthesis")
        assert result == ("anthropic", "claude-haiku-4-5-20251001")

    def test_bad_format_no_colon_raises(self):
        with patch.dict(os.environ, {"LLM_ROLE_ROUTER": "groqopenai"}):
            with pytest.raises(LLMConfigError, match="not in 'provider:model' format"):
                _parse_role_env("router")

    def test_unknown_provider_raises(self):
        with patch.dict(os.environ, {"LLM_ROLE_ROUTER": "cohere:command-r"}):
            with pytest.raises(LLMConfigError, match="unsupported provider"):
                _parse_role_env("router")

    def test_stub_provider_accepted(self):
        with patch.dict(os.environ, {"LLM_ROLE_ROUTER": "stub:stub"}):
            result = _parse_role_env("router")
        assert result == ("stub", "stub")


# ---------------------------------------------------------------------------
# load_adapter_for_role
# ---------------------------------------------------------------------------


class TestLoadAdapterForRole:
    def test_stub_provider_returns_stub_adapter(self):
        with patch.dict(os.environ, {"LLM_ROLE_ROUTER": "stub:stub"}):
            adapter = load_adapter_for_role("router")
        assert isinstance(adapter, StubAdapter)
        assert adapter.role == "router"

    def test_missing_api_key_raises(self):
        env = {"LLM_ROLE_SYNTHESIS": "groq:openai/gpt-oss-20b"}
        with patch.dict(os.environ, env):
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
                load_adapter_for_role("synthesis")

    def test_fallback_logs_warning(self, caplog):
        import logging
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_ROLE_DEFAULT", None)
            # Patch get_llm_client to avoid needing a real provider.
            with patch("app.models.llm._legacy_adapter") as mock_legacy:
                mock_legacy.return_value = _stub(role="default")
                with caplog.at_level(logging.WARNING, logger="app.models.llm"):
                    load_adapter_for_role("default")
        assert "LLM_ROLE_DEFAULT is not set" in caplog.text


# ---------------------------------------------------------------------------
# Greeting feature flag
# ---------------------------------------------------------------------------


def _load_pipeline_progress_module(env_override: dict):
    """
    Load pipeline_progress.py in isolation (bypassing app/core/__init__.py
    which needs SQLAlchemy).  Returns the freshly loaded module object.
    """
    import importlib.util
    import sys

    mod_name = "_pp_isolated_test"
    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(os.path.dirname(__file__), "../../app/core/pipeline_progress.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so dataclass annotations resolve correctly.
    sys.modules[mod_name] = mod
    try:
        with patch.dict(os.environ, env_override):
            spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)
    return mod


class TestGreetingFeatureFlag:
    def test_pipeline_progress_no_greeting_by_default(self):
        """With ENABLE_GREETING_NODE unset, 'greeting' must not appear."""
        clean_env = {k: v for k, v in os.environ.items() if k != "ENABLE_GREETING_NODE"}
        with patch.dict(os.environ, clean_env, clear=True):
            pp = _load_pipeline_progress_module({})
        node_names = [row[0] for row in pp.PIPELINE_NODE_DEFS]
        assert "greeting" not in node_names
        assert node_names[0] == "load_patient_context"

    def test_pipeline_progress_greeting_when_flagged(self):
        """With ENABLE_GREETING_NODE=1, 'greeting' is first."""
        pp = _load_pipeline_progress_module({"ENABLE_GREETING_NODE": "1"})
        node_names = [row[0] for row in pp.PIPELINE_NODE_DEFS]
        assert node_names[0] == "greeting"
        assert node_names[1] == "load_patient_context"
