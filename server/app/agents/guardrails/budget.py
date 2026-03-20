"""
Budget Guardrail — enforce LLM call limits per workflow run.

Prevents runaway agent loops from consuming unbounded API credits.
Applied as a pre-check before any LLM invocation.
"""

from __future__ import annotations

from typing import Any, Dict


class BudgetGuardrail:
    """
    Tracks and enforces LLM call budget within a single workflow run.

    Usage in a node::

        guardrail = BudgetGuardrail.from_state(state)
        if guardrail.can_call():
            response = llm.generate(prompt)
            guardrail.record_call()
            guardrail.write_to_state(state)
        else:
            # use template fallback
    """

    def __init__(self, max_calls: int = 30, calls_used: int = 0):
        self.max_calls = max_calls
        self.calls_used = calls_used

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> "BudgetGuardrail":
        """Build guardrail from current GraphState controls."""
        controls = state.get("controls", {})
        budget = controls.get("budget", {})
        return cls(
            max_calls=budget.get("max_total_llm_calls", 30),
            calls_used=budget.get("llm_calls_used", 0),
        )

    # ── Checks ──────────────────────────────────────────────────────────────

    def can_call(self, n: int = 1) -> bool:
        """Return True if at least ``n`` more LLM calls are within budget."""
        return (self.calls_used + n) <= self.max_calls

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    @property
    def exhausted(self) -> bool:
        return self.calls_used >= self.max_calls

    # ── Mutations ───────────────────────────────────────────────────────────

    def record_call(self, n: int = 1) -> None:
        """Record that ``n`` LLM calls were made."""
        self.calls_used += n

    def write_to_state(self, state: Dict[str, Any]) -> None:
        """Persist budget counters back into GraphState."""
        controls = state.setdefault("controls", {})
        budget = controls.setdefault("budget", {})
        budget["llm_calls_used"] = self.calls_used
        budget["max_total_llm_calls"] = self.max_calls
