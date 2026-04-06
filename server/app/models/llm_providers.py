"""
LLM Provider Factory - Unified interface for multiple LLM endpoints.

Supports:
- Groq (default)
- OpenAI
- Anthropic Claude
- Google Gemini
- OpenRouter
"""

import logging
from typing import Optional, Dict, List, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response from LLM."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider has valid API key."""
        pass


class GroqProvider(LLMProvider):
    """Groq API provider."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GROQ_API_KEY is required")
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response using Groq."""
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 2000),
            temperature=kwargs.get("temperature", 0.1),
        )
        return response.choices[0].message.content

    def is_available(self) -> bool:
        """Check if Groq client is initialized."""
        return self.client is not None


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4-turbo-preview"

    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response using OpenAI."""
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 2000),
            temperature=kwargs.get("temperature", 0.1),
        )
        return response.choices[0].message.content

    def is_available(self) -> bool:
        """Check if OpenAI client is initialized."""
        return self.client is not None


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-3-opus-20240229"

    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response using Claude."""
        message = self.client.messages.create(
            model=model or self.model,
            max_tokens=kwargs.get("max_tokens", 2000),
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def is_available(self) -> bool:
        """Check if Anthropic client is initialized."""
        return self.client is not None


class GoogleProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is required")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.client = genai.GenerativeModel("gemini-pro")

    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response using Google Gemini."""
        response = self.client.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": kwargs.get("max_tokens", 2000),
                "temperature": kwargs.get("temperature", 0.1),
            },
        )
        return response.text

    def is_available(self) -> bool:
        """Check if Google client is initialized."""
        return self.client is not None


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider - supports many models."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        from openai import OpenAI
        self.client = OpenAI(
            base_url="https://openrouter.io/api/v1",
            api_key=api_key,
        )
        self.model = "meta-llama/llama-2-70b-chat"

    def generate(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate response using OpenRouter."""
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 2000),
            temperature=kwargs.get("temperature", 0.1),
        )
        return response.choices[0].message.content

    def is_available(self) -> bool:
        """Check if OpenRouter client is initialized."""
        return self.client is not None


class LLMProviderFactory:
    """Factory for creating and managing LLM providers."""

    PROVIDERS = {
        "groq": GroqProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "openrouter": OpenRouterProvider,
    }

    @staticmethod
    def get_available_providers(settings) -> Dict[str, bool]:
        """
        Get list of available providers based on environment variables.

        Returns: Dict mapping provider name to availability status
        """
        available = {}
        available["groq"] = bool(settings.groq_api_key)
        available["openai"] = bool(settings.openai_api_key)
        available["anthropic"] = bool(settings.anthropic_api_key)
        available["google"] = bool(settings.google_api_key)
        available["openrouter"] = bool(settings.openrouter_api_key)
        return available

    @staticmethod
    def create(provider_name: str, settings) -> LLMProvider:
        """
        Create an LLM provider instance.

        Args:
            provider_name: Name of the provider (groq, openai, anthropic, google, openrouter)
            settings: Application settings containing API keys

        Returns:
            Provider instance

        Raises:
            ValueError: If provider is not found or API key is missing
        """
        provider_name = provider_name.lower().strip()

        if provider_name not in LLMProviderFactory.PROVIDERS:
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available: {list(LLMProviderFactory.PROVIDERS.keys())}"
            )

        ProviderClass = LLMProviderFactory.PROVIDERS[provider_name]

        if provider_name == "groq":
            return ProviderClass(settings.groq_api_key)
        elif provider_name == "openai":
            return ProviderClass(settings.openai_api_key)
        elif provider_name == "anthropic":
            return ProviderClass(settings.anthropic_api_key)
        elif provider_name == "google":
            return ProviderClass(settings.google_api_key)
        elif provider_name == "openrouter":
            return ProviderClass(settings.openrouter_api_key)

    @staticmethod
    def get_default_provider(settings) -> str:
        """
        Get the default provider based on available API keys.

        Priority order:
        1. User-selected (LLM_PROVIDER env var)
        2. Groq (default fallback)
        3. First available provider

        Returns:
            Provider name
        """
        # Check if user explicitly selected a provider
        if settings.llm_provider:
            selected = settings.llm_provider.lower().strip()
            available = LLMProviderFactory.get_available_providers(settings)
            if available.get(selected):
                return selected
            logger.warning(
                f"Selected provider {selected} not available (missing API key). "
                f"Falling back to default."
            )

        # Priority: Groq > OpenAI > Anthropic > Google > OpenRouter
        if settings.groq_api_key:
            return "groq"
        elif settings.openai_api_key:
            return "openai"
        elif settings.anthropic_api_key:
            return "anthropic"
        elif settings.google_api_key:
            return "google"
        elif settings.openrouter_api_key:
            return "openrouter"

        raise ValueError(
            "No LLM provider API keys found. "
            "Please set at least one of: GROQ_API_KEY, OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENROUTER_API_KEY"
        )
