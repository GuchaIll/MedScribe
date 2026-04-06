"""
LLM Provider configuration endpoints.

Allows clients to:
1. Get available LLM providers
2. Select an LLM provider for the session
3. Validate provider configuration
"""

import logging
from typing import Annotated
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.config.settings import get_settings, Settings
from app.models.llm_providers import LLMProviderFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/llm", tags=["LLM Configuration"])


class ProviderSelectRequest(BaseModel):
    provider_name: str


PROVIDER_DESCRIPTIONS = {
    "groq": {
        "display_name": "Groq",
        "description": "Fast Groq API - best for latency-sensitive applications",
    },
    "openai": {
        "display_name": "OpenAI",
        "description": "OpenAI GPT models",
    },
    "anthropic": {
        "display_name": "Anthropic Claude",
        "description": "Anthropic Claude models - excellent reasoning",
    },
    "google": {
        "display_name": "Google Gemini",
        "description": "Google Gemini models - multimodal capabilities",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "description": "OpenRouter - access to 100+ open source models",
    },
}

PROVIDER_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4-turbo-preview",
    "anthropic": "claude-3-opus-20240229",
    "google": "gemini-pro",
    "openrouter": "meta-llama/llama-2-70b-chat",
}


@router.get("/providers")
async def get_available_providers(
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Get list of available LLM providers based on configured API keys.

    Returns: Dict with available providers and default provider
    """
    try:
        available = LLMProviderFactory.get_available_providers(settings)
        default = None
        try:
            default = LLMProviderFactory.get_default_provider(settings)
        except ValueError:
            # No keys configured yet.
            default = None

        providers = []
        for name, is_available in available.items():
            info = PROVIDER_DESCRIPTIONS.get(name, {})
            provider = {
                "name": name,
                "display_name": info.get("display_name", name.capitalize()),
                "description": info.get(
                    "description", f"{name.capitalize()} LLM API provider"
                ),
                "available": is_available,
                "default_model": PROVIDER_MODELS.get(name, ""),
            }
            providers.append(provider)

        return {
            "providers": providers,
            "default_provider": default,
            "selected_provider": settings.llm_provider or default,
        }
    except Exception as e:
        logger.error(f"Error getting available providers: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving providers: {str(e)}",
        )


@router.post("/provider/select")
async def select_provider(
    payload: ProviderSelectRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Select an LLM provider for the session.

    Args:
        provider_name: Name of the provider (groq, openai, anthropic, google, openrouter)

    Returns: Confirmation with selected provider details
    """
    provider_name = payload.provider_name.lower().strip()

    try:
        # Validate provider exists
        if provider_name not in LLMProviderFactory.PROVIDERS:
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available: {list(LLMProviderFactory.PROVIDERS.keys())}"
            )

        # Validate provider is available (has API key)
        available = LLMProviderFactory.get_available_providers(settings)
        if not available.get(provider_name):
            raise ValueError(
                f"Provider '{provider_name}' is not available - missing API key"
            )

        # Note: In a production setting, this would set the provider on the user's session
        # For now, return the selection confirmation
        info = PROVIDER_DESCRIPTIONS.get(provider_name, {})

        return {
            "success": True,
            "message": f"Selected {info.get('display_name', provider_name)} as LLM provider",
            "provider": provider_name,
            "display_name": info.get("display_name", provider_name.capitalize()),
            "model": PROVIDER_MODELS.get(provider_name, ""),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error selecting provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_llm_status(settings: Annotated[Settings, Depends(get_settings)]):
    """
    Get current LLM configuration and health status.

    Returns: LLM service status and current provider
    """
    try:
        available = LLMProviderFactory.get_available_providers(settings)
        default = None
        try:
            default = LLMProviderFactory.get_default_provider(settings)
        except ValueError:
            default = None

        has_any_key = any(available.values())

        return {
            "status": "configured" if has_any_key else "unconfigured",
            "default_provider": default,
            "current_provider": settings.llm_provider or default,
            "available_providers": available,
            "configured_keys_count": sum(1 for v in available.values() if v),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "available_providers": {},
        }
