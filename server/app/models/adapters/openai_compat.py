"""
OpenAI-compatible adapter (Groq / OpenAI / Gemini-compat / OpenRouter).

Requires openai>=1.40 (adds beta.chat.completions.parse for structured output).
Every call emits an LLM span via build_llm_attrs + TraceSpan from #48.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError

from app.models.llm import LLMConfigError, ToolCallProposal

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter:
    """
    LLMAdapter implementation for providers that expose the OpenAI REST API:
    OpenAI, Groq, Gemini-compat endpoint, OpenRouter (synthetic data only).

    PHI note: do not pass PHI to OpenRouter. Real patient data requires a
    provider with a signed BAA (OpenAI, Groq with written consent, Anthropic,
    Google Vertex). Enforcement is a configuration policy, not adapter code.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        role: str,
        provider: str = "openai",
        base_url: Optional[str] = None,
    ) -> None:
        if not model:
            raise LLMConfigError(
                f"OpenAICompatibleAdapter: model must be a non-empty string, got {model!r}"
            )
        if not api_key:
            raise LLMConfigError(
                f"OpenAICompatibleAdapter: api_key is required for provider {provider!r}"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "openai>=1.40 is required for OpenAICompatibleAdapter. "
                "Run: pip install 'openai>=1.40'"
            ) from exc

        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        self._client = OpenAI(**kwargs)
        self._model = model
        self._role = role
        self._provider = provider
        logger.debug(
            "OpenAICompatibleAdapter: provider=%s model=%s role=%s",
            provider,
            model,
            role,
        )

    # ------------------------------------------------------------------
    # Protocol properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return self._provider

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

        start = time.monotonic()
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        duration_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage

        self._emit_span(
            prompt_id="<inline>",
            prompt_version=0,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=0,
            cost_usd=0.0,
            schema_valid=True,
            repair_retry=0,
            finish_reason=choice.finish_reason or "stop",
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
        JSON mode + Pydantic validation.

        On ValidationError: makes one repair retry (system message asking
        the model to fix its own output). Raises ValueError if the second
        attempt also fails.
        """
        if not messages:
            raise ValueError("generate_structured: messages must be a non-empty list")

        start = time.monotonic()
        repair_retry = 0
        schema_valid = True

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        raw = choice.message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

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

            repair_messages = list(messages) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your response did not conform to the expected JSON schema. "
                        f"Please correct it. Schema: {schema.model_json_schema()}"
                    ),
                },
            ]
            repair_response = self._client.chat.completions.create(
                **{**kwargs, "messages": repair_messages}
            )
            repair_raw = repair_response.choices[0].message.content or ""
            repair_usage = repair_response.usage
            input_tokens += repair_usage.prompt_tokens if repair_usage else 0
            output_tokens += repair_usage.completion_tokens if repair_usage else 0

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
            prompt_id="<inline>",
            prompt_version=0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=0,
            cost_usd=0.0,
            schema_valid=schema_valid,
            repair_retry=repair_retry,
            finish_reason=choice.finish_reason or "stop",
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
        Native tool calling.

        Returns text if the model chose not to call a tool, or a list of
        ToolCallProposal instances. The runtime always executes tools itself.
        """
        if not messages:
            raise ValueError("generate_with_tools: messages must be a non-empty list")
        if not tools:
            raise ValueError("generate_with_tools: tools must be a non-empty list")

        start = time.monotonic()
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": list(tools),
            "tool_choice": tool_choice,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage
        duration_ms = (time.monotonic() - start) * 1000

        self._emit_span(
            prompt_id="<inline>",
            prompt_version=0,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=0,
            cost_usd=0.0,
            schema_valid=True,
            repair_retry=0,
            finish_reason=choice.finish_reason or "stop",
            duration_ms=duration_ms,
        )

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            proposals = [
                ToolCallProposal(
                    tool_name=tc.function.name,
                    tool_args=json.loads(tc.function.arguments or "{}"),
                    tool_call_id=tc.id,
                )
                for tc in choice.message.tool_calls
            ]
            logger.debug(
                "generate_with_tools: %d proposal(s) from %s/%s",
                len(proposals),
                self._provider,
                self._model,
            )
            return proposals

        return choice.message.content or ""

    # ------------------------------------------------------------------
    # Span emission
    # ------------------------------------------------------------------

    def _emit_span(
        self,
        *,
        prompt_id: str,
        prompt_version: int,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
        cost_usd: float,
        schema_valid: bool,
        repair_retry: int,
        finish_reason: str,
        duration_ms: float,
    ) -> None:
        """Emit an LLM span via the #48 trace infrastructure (best-effort)."""
        try:
            from app.agents.trace_contracts import TraceSpan, TRACE_SCHEMA_VERSION
            from app.agents.tracing.spans import (
                build_llm_attrs,
                new_span_id,
                new_trace_id,
                utcnow_iso,
            )
            from app.agents.tracing.sinks import get_metrics

            span = TraceSpan(
                trace_schema_version=TRACE_SCHEMA_VERSION,
                trace_id=new_trace_id(),
                span_id=new_span_id(),
                parent_span_id=None,
                kind="synthesis",  # best-effort default; callers may override
                name=f"llm.{self._role}",
                session_id="<unknown>",
                started_at=utcnow_iso(),
                duration_ms=round(duration_ms, 2),
                status="ok",
                attributes=build_llm_attrs(
                    prompt_id=prompt_id,
                    prompt_version=str(prompt_version),
                    prompt_template_sha="",
                    model_role=self._role,
                    provider=self._provider,
                    model=self._model,
                    temperature=0.0,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    context_tokens_by_segment={},
                    schema_valid=schema_valid,
                    repair_retry=repair_retry,
                    finish_reason=finish_reason,
                ),
            )
            get_metrics().record_llm_call(
                role=self._role,
                provider=self._provider,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
            )
            logger.debug(
                "LLM span emitted: role=%s provider=%s model=%s tokens=%d+%d",
                self._role,
                self._provider,
                self._model,
                input_tokens,
                output_tokens,
            )
        except Exception:  # pragma: no cover
            # Span emission must never crash the adapter call.
            logger.exception(
                "OpenAICompatibleAdapter._emit_span: failed (non-fatal); "
                "role=%s provider=%s model=%s",
                self._role,
                self._provider,
                self._model,
            )
