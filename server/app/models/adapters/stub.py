"""
Stub adapter — scripted responses for tests and Phase 1A stubs.

Zero network calls. Every generate* method reads from a pre-seeded queue
of responses. When the queue is exhausted, raises StubAdapter.Exhausted so
test authors see over-calls explicitly (no silent empty returns).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Type, Union

from pydantic import BaseModel, ValidationError

from app.models.llm import ToolCallProposal

logger = logging.getLogger(__name__)

# Type aliases for scripted responses
ScriptedText = str
ScriptedJSON = Dict[str, Any]
ScriptedToolCalls = List[Dict[str, Any]]  # list of {tool_name, tool_args}
ScriptedResponse = Union[ScriptedText, ScriptedJSON, ScriptedToolCalls]


class StubAdapter:
    """
    Scripted LLMAdapter for tests and 1A stubs.

    Usage:
        adapter = StubAdapter(
            responses=["first answer", {"field": "value"}, [{"tool_name": "x", "tool_args": {}}]],
            role="synthesis",
        )
        result = adapter.generate([...])   # returns "first answer"
        result = adapter.generate_structured([...], MyModel)  # returns MyModel(field="value")
        result = adapter.generate_with_tools([...], tools=[...])  # returns [ToolCallProposal]
    """

    class Exhausted(RuntimeError):
        """Raised when generate* is called but no scripted responses remain."""

    def __init__(
        self,
        *,
        responses: Optional[List[ScriptedResponse]] = None,
        role: str = "stub",
    ) -> None:
        self._queue: Deque[ScriptedResponse] = deque(responses or [])
        self._role = role
        self._calls: List[Dict[str, Any]] = []  # call log for assertions

    # ------------------------------------------------------------------
    # Protocol properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model(self) -> str:
        return "stub"

    @property
    def role(self) -> str:
        return self._role

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def add_response(self, response: ScriptedResponse) -> None:
        """Append a scripted response to the queue."""
        self._queue.append(response)

    @property
    def call_count(self) -> int:
        return len(self._calls)

    @property
    def calls(self) -> List[Dict[str, Any]]:
        """Ordered record of every generate* call with its method name and messages."""
        return list(self._calls)

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> str:
        if not messages:
            raise ValueError("generate: messages must be a non-empty list")

        scripted = self._next_response("generate")
        if isinstance(scripted, str):
            return scripted
        if isinstance(scripted, dict):
            return json.dumps(scripted)
        raise TypeError(
            f"StubAdapter.generate: expected str or dict response, got {type(scripted)}"
        )

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[BaseModel],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        if not messages:
            raise ValueError("generate_structured: messages must be a non-empty list")

        scripted = self._next_response("generate_structured")
        if isinstance(scripted, dict):
            try:
                return schema.model_validate(scripted)
            except ValidationError as exc:
                raise ValueError(
                    f"StubAdapter.generate_structured: scripted dict does not "
                    f"validate against {schema.__name__}: {exc}"
                ) from exc
        if isinstance(scripted, str):
            try:
                return schema.model_validate(json.loads(scripted))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(
                    f"StubAdapter.generate_structured: scripted str does not "
                    f"parse/validate as {schema.__name__}: {exc}"
                ) from exc
        if isinstance(scripted, BaseModel):
            return scripted
        raise TypeError(
            f"StubAdapter.generate_structured: expected dict, str, or BaseModel, "
            f"got {type(scripted)}"
        )

    def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: Sequence[Dict[str, Any]],
        *,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> "str | List[ToolCallProposal]":
        if not messages:
            raise ValueError("generate_with_tools: messages must be a non-empty list")
        if not tools:
            raise ValueError("generate_with_tools: tools must be a non-empty list")

        scripted = self._next_response("generate_with_tools")
        if isinstance(scripted, str):
            return scripted
        if isinstance(scripted, list) and scripted and isinstance(scripted[0], dict):
            return [
                ToolCallProposal(
                    tool_name=item["tool_name"],
                    tool_args=item.get("tool_args", {}),
                    tool_call_id=item.get("tool_call_id", uuid.uuid4().hex[:8]),
                )
                for item in scripted
            ]
        raise TypeError(
            f"StubAdapter.generate_with_tools: expected str or list-of-dicts, "
            f"got {type(scripted)}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _next_response(self, method: str) -> ScriptedResponse:
        self._calls.append({"method": method})
        if not self._queue:
            raise StubAdapter.Exhausted(
                f"StubAdapter: no scripted response left for call #{len(self._calls)} "
                f"(method={method}, role={self._role})"
            )
        return self._queue.popleft()
