"""
Budget-aware LLM adapter wrapper.

BudgetAwareLLMAdapter wraps any LLMAdapter with BudgetGuardrail so that
all three protocol methods (generate, generate_structured, generate_with_tools)
share the same per-run call cap.

Backward-compat export: LLMTool = BudgetAwareLLMAdapter (old import sites
continue to work; migrate them to BudgetAwareLLMAdapter in workflow issues).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel

from app.agents.guardrails.budget import BudgetGuardrail
from app.models.llm import BudgetExhaustedError, LLMAdapter, ToolCallProposal

logger = logging.getLogger(__name__)


class BudgetAwareLLMAdapter:
    """
    Wraps any LLMAdapter with per-run LLM call capping.

    Every call to generate / generate_structured / generate_with_tools
    checks the BudgetGuardrail *before* the network call and raises
    BudgetExhaustedError if the cap is hit.  After a successful call the
    guardrail is incremented.

    Usage (new callers)::

        adapter = load_adapter_for_role("synthesis")
        budget  = BudgetGuardrail(max_calls=30)
        llm     = BudgetAwareLLMAdapter(adapter, budget)
        text    = llm.generate([{"role": "user", "content": "..."}])

    Usage (from GraphState in a node)::

        budget = BudgetGuardrail.from_state(state)
        llm = BudgetAwareLLMAdapter(ctx.llm_adapter, budget)
        text = llm.generate(messages)
        budget.write_to_state(state)

    The ``budget`` object is mutated by this class.  If the caller holds a
    reference to it they can call ``budget.write_to_state(state)`` afterwards
    to persist the updated counters — BudgetAwareLLMAdapter does NOT write back
    to state itself.
    """

    def __init__(
        self,
        adapter: LLMAdapter,
        budget: Optional[BudgetGuardrail] = None,
    ) -> None:
        """
        Args:
            adapter: Any object satisfying the LLMAdapter protocol.
            budget:  BudgetGuardrail instance.  If None, a default 30-call
                     budget is created (adequate for tests and stubs; production
                     callers should pass one from BudgetGuardrail.from_state).
        """
        if adapter is None:
            raise ValueError("BudgetAwareLLMAdapter: adapter must not be None")
        self._adapter = adapter
        self._budget = budget if budget is not None else BudgetGuardrail(max_calls=30)
        logger.debug(
            "BudgetAwareLLMAdapter: adapter=%s role=%s max_calls=%d",
            type(adapter).__name__,
            adapter.role,
            self._budget.max_calls,
        )

    # ------------------------------------------------------------------
    # Forwarded properties (makes BudgetAwareLLMAdapter usable anywhere
    # an LLMAdapter is expected)
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return self._adapter.provider

    @property
    def model(self) -> str:
        return self._adapter.model

    @property
    def role(self) -> str:
        return self._adapter.role

    @property
    def budget(self) -> BudgetGuardrail:
        """Expose the guardrail so callers can write it back to state."""
        return self._budget

    # ------------------------------------------------------------------
    # Protocol methods — each gate on budget before the network call
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> str:
        self._check_budget("generate")
        result = self._adapter.generate(
            messages, max_tokens=max_tokens, temperature=temperature
        )
        self._budget.record_call()
        logger.debug(
            "BudgetAwareLLMAdapter.generate: calls_used=%d/%d",
            self._budget.calls_used,
            self._budget.max_calls,
        )
        return result

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[BaseModel],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        self._check_budget("generate_structured")
        result = self._adapter.generate_structured(
            messages, schema, max_tokens=max_tokens, temperature=temperature
        )
        self._budget.record_call()
        logger.debug(
            "BudgetAwareLLMAdapter.generate_structured: calls_used=%d/%d",
            self._budget.calls_used,
            self._budget.max_calls,
        )
        return result

    def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: Sequence[Dict[str, Any]],
        *,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> "str | List[ToolCallProposal]":
        self._check_budget("generate_with_tools")
        result = self._adapter.generate_with_tools(
            messages,
            tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self._budget.record_call()
        logger.debug(
            "BudgetAwareLLMAdapter.generate_with_tools: calls_used=%d/%d",
            self._budget.calls_used,
            self._budget.max_calls,
        )
        return result

    # ------------------------------------------------------------------
    # Legacy generate_response shim (old LLMTool / LLMClient callers)
    # ------------------------------------------------------------------

    def generate_response(
        self, prompt: str, max_tokens: Optional[int] = None
    ) -> str:
        """
        Backward-compat shim matching the old LLMClient.generate_response
        signature.  Delegates to generate() with a single user message.
        """
        return self.generate(
            [{"role": "user", "content": prompt}], max_tokens=max_tokens
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_budget(self, method: str) -> None:
        if self._budget.exhausted:
            raise BudgetExhaustedError(
                f"BudgetAwareLLMAdapter.{method}: LLM call budget exhausted "
                f"(calls_used={self._budget.calls_used}, "
                f"max_calls={self._budget.max_calls}, "
                f"role={self._adapter.role})"
            )


# ---------------------------------------------------------------------------
# Backward-compat alias (old import: from app.agents.tools.llm import LLMTool)
# ---------------------------------------------------------------------------

class LLMTool(BudgetAwareLLMAdapter):
    """
    Backward-compatible name.  Accepts the old LLMTool constructor signature
    (factory + max_calls) and wraps a StubAdapter-like default when no adapter
    is given, so existing tests that only test budget logic continue to work.

    Migrate call sites to BudgetAwareLLMAdapter in their workflow issues.
    """

    def __init__(
        self,
        factory=None,
        max_calls: int = 30,
        adapter: Optional[LLMAdapter] = None,
    ) -> None:
        if adapter is not None:
            resolved_adapter = adapter
        elif factory is not None:
            # factory() returns an LLMClient-like object; wrap it in a thin
            # LegacyClientAdapter so it satisfies the LLMAdapter protocol.
            resolved_adapter = _LegacyClientAdapter(factory(), role="default")
        else:
            # No adapter and no factory: build from load_adapter_for_role.
            try:
                from app.models.llm import load_adapter_for_role
                resolved_adapter = load_adapter_for_role("default")
            except Exception:
                logger.exception(
                    "LLMTool: load_adapter_for_role('default') failed; "
                    "using a StubAdapter so the object can be instantiated"
                )
                from app.models.adapters.stub import StubAdapter
                resolved_adapter = StubAdapter(role="default")

        super().__init__(resolved_adapter, BudgetGuardrail(max_calls=max_calls))
        # Keep old attribute names for legacy attribute access.
        self.max_calls = self._budget.max_calls

    # ------------------------------------------------------------------
    # Legacy attribute aliases
    # ------------------------------------------------------------------

    @property
    def calls_used(self) -> int:
        return self._budget.calls_used

    @property
    def budget_remaining(self) -> int:
        return self._budget.remaining

    @property
    def exhausted(self) -> bool:
        return self._budget.exhausted

    @property
    def budget_exhausted(self) -> bool:
        """Alias for backward compat (old tests use tool.budget_exhausted)."""
        return self._budget.exhausted

    # Old LLMTool had a .client property returning the raw LLMClient object.
    @property
    def client(self):  # type: ignore[override]
        """Legacy attribute. Returns the raw client from _LegacyClientAdapter, or the adapter."""
        if isinstance(self._adapter, _LegacyClientAdapter):
            return self._adapter._client
        return self._adapter

    # ------------------------------------------------------------------
    # Legacy generate signature: accepts a bare string prompt
    # ------------------------------------------------------------------

    def generate(  # type: ignore[override]
        self,
        messages_or_prompt,
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> str:
        """
        Backward-compat override: accepts either a bare string prompt or a
        messages list (new calling convention).

        Raises:
            ValueError: if prompt is empty.
            RuntimeError: if LLM budget exhausted (message contains "LLM budget exhausted").
        """
        if isinstance(messages_or_prompt, str):
            prompt = messages_or_prompt
            if not prompt or not prompt.strip():
                raise ValueError("Prompt cannot be empty")
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = messages_or_prompt

        try:
            return super().generate(messages, max_tokens=max_tokens, temperature=temperature)
        except BudgetExhaustedError as exc:
            raise RuntimeError(
                f"LLM budget exhausted: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Legacy convenience methods
    # ------------------------------------------------------------------

    def try_generate(
        self,
        prompt: str,
        *,
        fallback: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Attempt generate(); return fallback if budget is exhausted or the call
        raises an exception.  Returns None if no fallback is given and the call
        fails.
        """
        try:
            return self.generate(prompt, max_tokens=max_tokens)
        except (RuntimeError, BudgetExhaustedError):
            logger.warning(
                "LLMTool.try_generate: budget exhausted or call failed; "
                "returning fallback (role=%s)",
                self._adapter.role,
            )
            return fallback
        except Exception:
            logger.warning(
                "LLMTool.try_generate: LLM call raised an exception; "
                "returning fallback (role=%s)",
                self._adapter.role,
            )
            return fallback

    def sync_budget_to_state(self, state: Dict[str, Any]) -> None:
        """Persist budget counters into GraphState controls.budget."""
        self._budget.write_to_state(state)


class _LegacyClientAdapter:
    """
    Thin shim that makes an old LLMClient look like an LLMAdapter.
    Used only by the LLMTool backward-compat constructor.
    """

    def __init__(self, client: Any, role: str) -> None:
        self._client = client
        self._role = role

    @property
    def provider(self) -> str:
        return getattr(self._client, "provider", "legacy")

    @property
    def model(self) -> str:
        return getattr(self._client, "model_name", "legacy")

    @property
    def role(self) -> str:
        return self._role

    def generate(self, messages: List[Dict[str, str]], *, max_tokens=None, temperature=0.0) -> str:  # noqa: ARG002,W0221
        prompt = messages[-1]["content"] if messages else ""
        return self._client.generate_response(prompt, max_tokens=max_tokens)

    def generate_structured(self, messages, schema, *, max_tokens=None, temperature=0.0):
        raise NotImplementedError(
            "_LegacyClientAdapter.generate_structured: migrate to BudgetAwareLLMAdapter"
        )

    def generate_with_tools(self, messages, tools, *, tool_choice="auto", max_tokens=None, temperature=0.0):
        raise NotImplementedError(
            "_LegacyClientAdapter.generate_with_tools: migrate to BudgetAwareLLMAdapter"
        )
