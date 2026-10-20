"""
LLM adapter protocol and per-role model configuration.

§18.11 of the refactor plan: one LLMAdapter protocol with three concrete
implementations (OpenAICompatibleAdapter, AnthropicAdapter, StubAdapter) and
a per-role config loader (LLM_ROLE_<ROLE>=provider:model).

The legacy LLMClient class is kept as a compatibility shim so that existing
callers (summarizer.py, nodes/clean.py, agents/config.py) are unaffected until
they migrate to BudgetAwareLLMAdapter in their respective workflow issues.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Protocol, Sequence, Type, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class LLMConfigError(ValueError):
    """Raised when LLM role config is invalid or missing a required key."""


class BudgetExhaustedError(RuntimeError):
    """Raised by BudgetAwareLLMAdapter when the per-run call cap is hit."""


# ---------------------------------------------------------------------------
# Tool call proposal (§18.11 — model may only *propose* calls)
# ---------------------------------------------------------------------------


class ToolCallProposal:
    """
    Normalized representation of a tool call proposed by the model.

    Consumers:
      - planner runner (agents/planner/run.py, #58): reads tool_name + tool_args
      - grounding validator (agents/grounding/checks.py, #57): reads tool_call_id
        to correlate proposal to receipt

    This object is in-memory only and is never persisted to PostgreSQL.
    """

    __slots__ = ("tool_name", "tool_args", "tool_call_id")

    def __init__(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str,
    ) -> None:
        if not tool_name:
            raise LLMConfigError(
                f"ToolCallProposal: tool_name must be a non-empty string, got {tool_name!r}"
            )
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.tool_call_id = tool_call_id

    def __repr__(self) -> str:
        return (
            f"ToolCallProposal(tool_name={self.tool_name!r}, "
            f"tool_call_id={self.tool_call_id!r})"
        )


# ---------------------------------------------------------------------------
# LLM adapter protocol (§18.11)
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMAdapter(Protocol):
    """
    Structural protocol every adapter must satisfy.

    Methods:
      generate           — plain text completion
      generate_structured — JSON mode + Pydantic validation + one repair retry
      generate_with_tools — native tool calling; returns text OR ToolCallProposal[]

    Properties read by span builders and tests:
      provider  — e.g. "groq", "openai", "anthropic", "stub"
      model     — model identifier string
      role      — logical role name matching LLM_ROLE_* env var suffix
    """

    @property
    def provider(self) -> str:
        ...

    @property
    def model(self) -> str:
        ...

    @property
    def role(self) -> str:
        ...

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> str:
        """Return generated text. Raises on network / API error."""
        ...

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[BaseModel],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
    ) -> BaseModel:
        """
        Return a validated Pydantic model instance.

        Attempts JSON mode first; on schema validation failure makes one repair
        retry (asking the model to fix its own output). Raises ValueError if
        the second attempt also fails to validate.
        """
        ...

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
        Return either plain text (if the model chose not to call a tool)
        or a list of ToolCallProposal instances. The runtime always executes
        tools itself — proposals are only accepted, never trusted blindly.
        """
        ...


# ---------------------------------------------------------------------------
# Per-role model config (§18.11)
# ---------------------------------------------------------------------------

# Supported provider identifiers and their required env-var keys.
_PROVIDER_KEY_MAP: Dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "stub": "",  # no key required
}


def _parse_role_env(role: str) -> Optional[tuple[str, str]]:
    """
    Parse LLM_ROLE_<ROLE> env var.

    Format: "provider:model_name"
    Returns (provider, model_name) or None if the env var is not set.
    Raises LLMConfigError on bad format or unknown provider.
    """
    env_key = f"LLM_ROLE_{role.upper()}"
    raw = os.environ.get(env_key)
    if not raw:
        return None

    if ":" not in raw:
        raise LLMConfigError(
            f"{env_key}={raw!r} is not in 'provider:model' format. "
            f"Example: {env_key}=groq:openai/gpt-oss-20b"
        )

    provider, model_name = raw.split(":", 1)
    provider = provider.strip().lower()

    if provider not in _PROVIDER_KEY_MAP:
        raise LLMConfigError(
            f"{env_key}: unsupported provider {provider!r}. "
            f"Supported: {', '.join(_PROVIDER_KEY_MAP)}"
        )

    return provider, model_name.strip()


def load_adapter_for_role(role: str) -> "LLMAdapter":
    """
    Return an LLMAdapter configured for the given logical role.

    Role resolution order:
      1. LLM_ROLE_<ROLE>=provider:model  (preferred)
      2. Legacy get_llm_client() path     (fallback, logged at warning)

    Roles used today: router, planner, synthesis, judge, addressee.
    """
    from app.models.adapters.openai_compat import OpenAICompatibleAdapter
    from app.models.adapters.anthropic import AnthropicAdapter
    from app.models.adapters.stub import StubAdapter

    parsed = _parse_role_env(role)

    if parsed is None:
        logger.warning(
            "LLM_ROLE_%s is not set; falling back to legacy get_llm_client() path. "
            "Set LLM_ROLE_%s=provider:model to suppress this warning.",
            role.upper(),
            role.upper(),
        )
        return _legacy_adapter(role)

    provider, model_name = parsed
    api_key = _get_api_key(provider)

    if provider == "stub":
        return StubAdapter(role=role)

    if provider == "anthropic":
        return AnthropicAdapter(api_key=api_key, model=model_name, role=role)

    # openai, groq, openrouter — all OpenAI-compatible
    base_url = _openai_compat_base_url(provider)
    return OpenAICompatibleAdapter(
        api_key=api_key,
        model=model_name,
        role=role,
        provider=provider,
        base_url=base_url,
    )


def _get_api_key(provider: str) -> str:
    env_key = _PROVIDER_KEY_MAP.get(provider, "")
    if not env_key:
        return ""
    key = os.environ.get(env_key, "")
    if not key:
        raise LLMConfigError(
            f"Provider {provider!r} requires {env_key} to be set in the environment."
        )
    return key


def _openai_compat_base_url(provider: str) -> Optional[str]:
    urls: Dict[str, str] = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        # "openai" uses the SDK default (no override needed)
    }
    return urls.get(provider)


def _legacy_adapter(role: str) -> "LLMAdapter":
    """Wrap the legacy LLMClient in a thin LegacyCompatAdapter."""
    from app.models.adapters.openai_compat import OpenAICompatibleAdapter
    from app.models.adapters.anthropic import AnthropicAdapter
    from .registry import get_llm_client

    packed = get_llm_client()
    provider = packed.get("provider", "openai")
    model_name = packed.get("model_name", "unknown")

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        return AnthropicAdapter(api_key=api_key, model=model_name, role=role)

    base_url = _openai_compat_base_url(provider)
    api_key = _get_api_key_for_legacy(provider)
    return OpenAICompatibleAdapter(
        api_key=api_key,
        model=model_name,
        role=role,
        provider=provider,
        base_url=base_url,
    )


def _get_api_key_for_legacy(provider: str) -> str:
    env_map = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    env_key = env_map.get(provider, "")
    return os.environ.get(env_key, "") if env_key else ""


# ---------------------------------------------------------------------------
# Legacy LLMClient compatibility shim
# ---------------------------------------------------------------------------


class LLMClient:
    """
    Backward-compatible shim. Existing callers (summarizer.py, nodes/clean.py,
    agents/config.py) continue to work unchanged.

    Delegates to load_adapter_for_role("default") which falls back to the legacy
    get_llm_client() path. Migrate callers to BudgetAwareLLMAdapter in their
    respective workflow issues (#56, #58, #61).
    """

    def __init__(self) -> None:
        try:
            self._adapter: LLMAdapter = load_adapter_for_role("default")
        except Exception:
            logger.exception(
                "LLMClient compat shim: load_adapter_for_role('default') failed; "
                "falling back to registry"
            )
            from .registry import get_llm_client
            packed = get_llm_client()
            self._packed = packed
            self._adapter = None  # type: ignore[assignment]

    def generate_response(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Thin shim over LLMAdapter.generate (single user message)."""
        if self._adapter is not None:
            return self._adapter.generate(
                [{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
        # Absolute last resort: delegate to old monolithic LLMClient logic
        return _legacy_generate_response(self._packed, prompt, max_tokens)


def _legacy_generate_response(
    packed: Dict[str, Any], prompt: str, max_tokens: Optional[int]
) -> str:
    """Inline fallback replicating old LLMClient.generate_response logic."""
    model_type = packed["type"]
    provider = packed.get("provider")
    model = packed["model"]
    model_name = packed.get("model_name")

    if model_type == "api":
        if provider in ("groq", "openai", "openrouter"):
            kwargs: Dict[str, Any] = {
                "messages": [{"role": "user", "content": prompt}],
                "model": model_name,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            chat_completion = model.chat.completions.create(**kwargs)
            return chat_completion.choices[0].message.content

        if provider == "anthropic":
            message = model.messages.create(
                model=model_name,
                max_tokens=max_tokens or 600,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text

        if provider == "google":
            response = model.generate_content(prompt)
            return response.text

        raise ValueError(f"Unsupported API provider: {provider}")

    raise ValueError(f"Unsupported model type: {model_type}")
