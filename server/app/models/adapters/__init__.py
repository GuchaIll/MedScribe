"""
LLM adapter implementations.

Exports: OpenAICompatibleAdapter, AnthropicAdapter, StubAdapter.
Import via: from app.models.adapters import OpenAICompatibleAdapter
"""

from .anthropic import AnthropicAdapter
from .openai_compat import OpenAICompatibleAdapter
from .stub import StubAdapter

__all__ = [
    "AnthropicAdapter",
    "OpenAICompatibleAdapter",
    "StubAdapter",
]
