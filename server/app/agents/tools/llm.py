"""
LLM Tool — budget-aware wrapper for LLM calls within agent nodes.

Tracks invocation count against the ``controls.budget`` in GraphState
so guardrails can enforce a per-run token/call cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from app.models.llm import LLMClient

logger = logging.getLogger(__name__)


class LLMTool:
    """
    Budget-aware LLM invocation tool.

    Nodes should use this instead of importing ``LLMClient`` directly
    so that total LLM usage is tracked and capped per workflow run.
    """

    def __init__(
        self,
        factory: Callable[[], LLMClient] | None = None,
        max_calls: int = 30,
    ) -> None:
        """
        Initialize LLM tool.

        Args:
            factory: Optional factory function to create LLMClient
            max_calls: Maximum number of LLM calls allowed per workflow
        """
        self._factory = factory
        self._client: Optional[LLMClient] = None
        self.max_calls = max_calls
        self.calls_used = 0
        logger.debug(f"LLMTool initialized with max_calls={max_calls}")

    @property
    def client(self) -> LLMClient:
        """Get or create LLM client instance."""
        if self._client is None:
            if self._factory is not None:
                self._client = self._factory()
                logger.debug("LLMClient created via factory")
            else:
                from app.models.llm import LLMClient as _LLMClient
                self._client = _LLMClient()
                logger.debug("LLMClient created via default constructor")
        return self._client

    @property
    def budget_remaining(self) -> int:
        """Get remaining LLM call budget."""
        return max(0, self.max_calls - self.calls_used)

    @property
    def budget_exhausted(self) -> bool:
        """Check if budget has been exhausted."""
        return self.calls_used >= self.max_calls

    def generate(self, prompt: str) -> str:
        """
        Generate a response and increment the call counter.

        Args:
            prompt: Prompt to send to LLM

        Returns:
            Generated response text

        Raises:
            RuntimeError: If budget is exhausted
            ValueError: If prompt is empty
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        if self.budget_exhausted:
            logger.error(f"LLM budget exhausted: {self.calls_used}/{self.max_calls}")
            raise RuntimeError(
                f"LLM budget exhausted: {self.calls_used}/{self.max_calls} calls used"
            )

        logger.debug(f"Generating with LLM (call {self.calls_used + 1}/{self.max_calls})")
        response = self.client.generate_response(prompt)
        self.calls_used += 1
        logger.debug(f"LLM call succeeded. Budget remaining: {self.budget_remaining}")
        return response

    def try_generate(self, prompt: str, fallback: str = "") -> str:
        """
        Attempt to generate; return fallback instead of raising on budget exhausted.

        Args:
            prompt: Prompt to send to LLM
            fallback: Fallback response if generation fails

        Returns:
            Generated response or fallback
        """
        try:
            return self.generate(prompt)
        except RuntimeError as e:
            logger.warning(f"LLM budget exhausted, returning fallback: {e}")
            return fallback
        except Exception as e:
            logger.warning(f"LLM generation failed, returning fallback: {e}")
            return fallback

    def sync_budget_to_state(self, state: dict[str, Any]) -> None:
        """
        Write current usage back into state["controls"]["budget"].

        Args:
            state: Workflow state dictionary to update
        """
        controls = state.setdefault("controls", {})
        budget = controls.setdefault("budget", {})
        budget["llm_calls_used"] = self.calls_used
        budget["max_total_llm_calls"] = self.max_calls
        logger.debug(f"Budget synced to state: {self.calls_used}/{self.max_calls}")
