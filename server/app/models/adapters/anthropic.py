"""
Anthropic adapter.

Requires anthropic>=0.25 (adds tool-use support).
Every call emits an LLM span via build_llm_attrs + TraceSpan from #48.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError

from app.models.llm import LLMConfigError, ToolCallProposal

logger = logging.getLogger(__name__)


class AnthropicAdapter:
    """
    LLMAdapter implementation for Anthropic Claude models.

    PHI note: Anthropic offers a Business Associate Agreement; production use
    with real patient data requires one to be in place before deployment.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        role: str,
    ) -> None:
        if not model:
            raise LLMConfigError(
                f"AnthropicAdapter: model must be a non-empty string, got {model!r}"
            )
        if not api_key:
            raise LLMConfigError(
                "AnthropicAdapter: api_key is required (set ANTHROPIC_API_KEY)"
            )

        try:
            import anthropic as _anthropic
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "anthropic>=0.25 is required for AnthropicAdapter. "
                "Run: pip install 'anthropic>=0.25'"
            ) from exc

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._role = role
        logger.debug("AnthropicAdapter: model=%s role=%s", model, role)

    # ------------------------------------------------------------------
    # Protocol properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    @property
    def role(self) -> str:
        return self._role

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
        """Plain text completion. Emits an LLM span."""
        if not messages:
            raise ValueError("generate: messages must be a non-empty list")

        system, user_messages = _split_system(messages)
        start = time.monotonic()

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        duration_ms = (time.monotonic() - start) * 1000
        text = response.content[0].text if response.content else ""
        usage = response.usage

        self._emit_span(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            schema_valid=True,
            repair_retry=0,
            finish_reason=response.stop_reason or "end_turn",
            duration_ms=duration_ms,
        )
        return text

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[BaseModel],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        """
        JSON mode via a system-level instruction + Pydantic validation.
        One repair retry on ValidationError.
        """
        if not messages:
            raise ValueError("generate_structured: messages must be a non-empty list")

        system, user_messages = _split_system(messages)
        json_instruction = (
            f"Respond with valid JSON that matches this schema exactly: "
            f"{schema.model_json_schema()}"
        )
        combined_system = f"{system}\n\n{json_instruction}" if system else json_instruction

        start = time.monotonic()
        repair_retry = 0
        schema_valid = True

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "messages": user_messages,
            "system": combined_system,
        }

        response = self._client.messages.create(**kwargs)
        raw = response.content[0].text if response.content else ""
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens

        try:
            parsed_json = json.loads(raw)
            result = schema.model_validate(parsed_json)
        except (json.JSONDecodeError, ValidationError) as first_exc:
            logger.warning(
                "generate_structured: validation failed on first attempt "
                "(role=%s model=%s schema=%s err=%s); attempting repair",
                self._role,
                self._model,
                schema.__name__,
                first_exc,
            )
            schema_valid = False
            repair_retry = 1

            repair_messages = list(user_messages) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your response did not conform to the expected JSON schema. "
                        "Please correct it and respond with valid JSON only."
                    ),
                },
            ]
            repair_response = self._client.messages.create(
                **{**kwargs, "messages": repair_messages}
            )
            repair_raw = repair_response.content[0].text if repair_response.content else ""
            input_tokens += repair_response.usage.input_tokens
            output_tokens += repair_response.usage.output_tokens

            try:
                result = schema.model_validate(json.loads(repair_raw))
                schema_valid = True
            except (json.JSONDecodeError, ValidationError) as second_exc:
                raise ValueError(
                    f"generate_structured: repair retry also failed "
                    f"(role={self._role} schema={schema.__name__}): {second_exc}"
                ) from second_exc

        duration_ms = (time.monotonic() - start) * 1000
        self._emit_span(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            schema_valid=schema_valid,
            repair_retry=repair_retry,
            finish_reason=response.stop_reason or "end_turn",
            duration_ms=duration_ms,
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
        """
        Native Anthropic tool use.

        Converts OpenAI-style tool schemas to Anthropic format.
        Returns text if no tool was called, or ToolCallProposal list.
        """
        if not messages:
            raise ValueError("generate_with_tools: messages must be a non-empty list")
        if not tools:
            raise ValueError("generate_with_tools: tools must be a non-empty list")

        system, user_messages = _split_system(messages)
        anthropic_tools = [_to_anthropic_tool(t) for t in tools]

        # Anthropic tool_choice: {"type": "auto"} | {"type": "any"} | {"type": "tool", "name": ...}
        if tool_choice == "auto":
            anthr_tool_choice: Dict[str, Any] = {"type": "auto"}
        elif tool_choice == "required":
            anthr_tool_choice = {"type": "any"}
        else:
            anthr_tool_choice = {"type": "tool", "name": tool_choice}

        start = time.monotonic()
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "messages": user_messages,
            "tools": anthropic_tools,
            "tool_choice": anthr_tool_choice,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        usage = response.usage
        duration_ms = (time.monotonic() - start) * 1000

        self._emit_span(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            schema_valid=True,
            repair_retry=0,
            finish_reason=response.stop_reason or "end_turn",
            duration_ms=duration_ms,
        )

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if tool_use_blocks:
            proposals = [
                ToolCallProposal(
                    tool_name=b.name,
                    tool_args=b.input if isinstance(b.input, dict) else {},
                    tool_call_id=b.id,
                )
                for b in tool_use_blocks
            ]
            logger.debug(
                "generate_with_tools: %d proposal(s) from anthropic/%s",
                len(proposals),
                self._model,
            )
            return proposals

        text_blocks = [b for b in response.content if b.type == "text"]
        return text_blocks[0].text if text_blocks else ""

    # ------------------------------------------------------------------
    # Span emission
    # ------------------------------------------------------------------

    def _emit_span(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        schema_valid: bool,
        repair_retry: int,
        finish_reason: str,
        duration_ms: float,
    ) -> None:
        try:
            from app.agents.trace_contracts import TraceSpan, TRACE_SCHEMA_VERSION
            from app.agents.tracing.spans import (
                build_llm_attrs,
                new_span_id,
                new_trace_id,
                utcnow_iso,
            )
            from app.agents.tracing.sinks import get_metrics

            TraceSpan(
                trace_schema_version=TRACE_SCHEMA_VERSION,
                trace_id=new_trace_id(),
                span_id=new_span_id(),
                parent_span_id=None,
                kind="synthesis",
                name=f"llm.{self._role}",
                session_id="<unknown>",
                started_at=utcnow_iso(),
                duration_ms=round(duration_ms, 2),
                status="ok",
                attributes=build_llm_attrs(
                    prompt_id="<inline>",
                    prompt_version="0",
                    prompt_template_sha="",
                    model_role=self._role,
                    provider="anthropic",
                    model=self._model,
                    temperature=0.0,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=0,
                    cost_usd=0.0,
                    context_tokens_by_segment={},
                    schema_valid=schema_valid,
                    repair_retry=repair_retry,
                    finish_reason=finish_reason,
                ),
            )
            get_metrics().record_llm_call(
                role=self._role,
                provider="anthropic",
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
        except Exception:  # pragma: no cover
            logger.exception(
                "AnthropicAdapter._emit_span: failed (non-fatal); role=%s model=%s",
                self._role,
                self._model,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_system(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
    """
    Separate a leading system message from user/assistant messages.
    Anthropic requires system content to be passed as a top-level parameter.
    """
    if messages and messages[0].get("role") == "system":
        return messages[0]["content"], list(messages[1:])
    return "", list(messages)


def _to_anthropic_tool(openai_tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert an OpenAI-style tool definition to Anthropic format.

    OpenAI:   {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic: {"name": ..., "description": ..., "input_schema": ...}
    """
    if "function" in openai_tool:
        fn = openai_tool["function"]
        return {
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        }
    # Already in Anthropic format or unknown shape — pass through.
    return openai_tool
