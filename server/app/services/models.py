"""
Model services for loading and managing ML models.

Services:
- LLMService: LLM inference (Groq, Ollama, etc.)
- WhisperService: Speech-to-Text with VAD
- EmbeddingService: Text embeddings for semantic search
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging
import asyncio
from functools import lru_cache

from app.config.settings import Settings, get_settings
from app.services.locator import Service

logger = logging.getLogger(__name__)


class LLMService(Service):
    """
    LLM service for inference with budget tracking.

    Supports:
    - Groq API (remote)
    - Ollama (local)
    - HuggingFace (remote or local)
    """

    def __init__(self, settings: Settings):
        """
        Initialize LLM service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.client = None
        self.call_count = 0
        self.model_name = settings.model.llm_name

    async def initialize(self) -> None:
        """Load and initialize LLM client."""
        logger.info(f"Initializing LLM service: {self.settings.model.llm_provider}")

        if self.settings.model.llm_provider == "groq":
            await self._initialize_groq()
        elif self.settings.model.llm_provider == "ollama":
            await self._initialize_ollama()
        else:
            raise ValueError(f"Unsupported LLM provider: {self.settings.model.llm_provider}")

    async def _initialize_groq(self) -> None:
        """Initialize Groq client."""
        try:
            from groq import Groq
        except ImportError:
            raise ImportError("groq package required for Groq LLM. Install: pip install groq")

        if not self.settings.groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        self.client = Groq(api_key=self.settings.groq_api_key)
        logger.info("Groq LLM client initialized")

    async def _initialize_ollama(self) -> None:
        """Initialize Ollama client."""
        try:
            from ollama import Client
        except ImportError:
            raise ImportError("ollama package required for local LLM. Install: pip install ollama")

        self.client = Client(host="http://localhost:11434")
        logger.info("Ollama LLM client initialized")

    async def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up LLM service")
        self.client = None

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Generate text using LLM.

        Args:
            prompt: Input prompt
            max_tokens: Max tokens in response (uses settings if not specified)
            temperature: Temperature for sampling (uses settings if not specified)

        Returns:
            Generated text

        Raises:
            RuntimeError: If budget exceeded or inference fails
            ValueError: If not initialized
        """
        if self.client is None:
            raise ValueError("LLMService not initialized")

        if self.call_count >= self.settings.model.llm_max_budget_per_run:
            raise RuntimeError(
                f"LLM call budget exceeded: {self.call_count}/{self.settings.model.llm_max_budget_per_run}"
            )

        max_tokens = max_tokens or self.settings.model.llm_max_tokens
        temperature = temperature or self.settings.model.llm_temperature

        self.call_count += 1
        logger.info(f"LLM call {self.call_count}: {self.model_name}")

        try:
            if self.settings.model.llm_provider == "groq":
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content
            else:
                # Ollama response handling
                response = await asyncio.to_thread(
                    self.client.generate,
                    model=self.model_name,
                    prompt=prompt,
                )
                return response["response"]
        except Exception as e:
            logger.error(f"LLM inference failed: {e}")
            raise

    def reset_budget(self) -> None:
        """Reset call counter for new session."""
        logger.debug("Resetting LLM budget counter")
        self.call_count = 0


class WhisperService(Service):
    """Speech-to-text service using OpenAI Whisper."""

    def __init__(self, settings: Settings):
        """
        Initialize Whisper service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.model = None

    async def initialize(self) -> None:
        """Load Whisper model."""
        logger.info(f"Initializing Whisper service: {self.settings.model.whisper_model}")

        try:
            import whisper
        except ImportError:
            raise ImportError("openai-whisper required. Install: pip install openai-whisper")

        self.model = await asyncio.to_thread(
            whisper.load_model,
            self.settings.model.whisper_model,
            device=self.settings.model.whisper_device,
        )
        logger.info("Whisper model loaded")

    async def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up Whisper service")
        if self.model is not None:
            # Unload model from memory
            if hasattr(self.model, "cpu"):
                self.model.cpu()
            del self.model
            self.model = None

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> dict:
        """
        Transcribe audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (e.g., "en", "es"). Auto-detect if None.

        Returns:
            Transcription result with text and segments
        """
        if self.model is None:
            raise ValueError("WhisperService not initialized")

        logger.info(f"Transcribing audio: {audio_path}")

        try:
            result = await asyncio.to_thread(
                self.model.transcribe,
                audio_path,
                language=language,
                compute_type=self.settings.model.whisper_compute_type,
            )
            return result
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            raise


class EmbeddingService(Service):
    """Embeddings service for semantic search and similarity."""

    def __init__(self, settings: Settings):
        """
        Initialize embedding service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.model = None

    async def initialize(self) -> None:
        """Load embedding model."""
        logger.info("Initializing embedding service")

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers required. Install: pip install sentence-transformers"
            )

        self.model = await asyncio.to_thread(
            SentenceTransformer,
            "all-MiniLM-L6-v2",
            device=self.settings.model.whisper_device,
        )
        logger.info("Embedding model loaded")

    async def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up embedding service")
        self.model = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for texts.

        Args:
            texts: List of text strings

        Returns:
            List of embedding vectors
        """
        if self.model is None:
            raise ValueError("EmbeddingService not initialized")

        logger.debug(f"Generating embeddings for {len(texts)} texts")

        try:
            embeddings = await asyncio.to_thread(
                self.model.encode,
                texts,
                convert_to_numpy=True,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise


# Singleton cache for services
@lru_cache(maxsize=None)
def get_llm_service(settings: Optional[Settings] = None) -> LLMService:
    """Get or create LLM service singleton."""
    settings = settings or get_settings()
    return LLMService(settings)


@lru_cache(maxsize=None)
def get_whisper_service(settings: Optional[Settings] = None) -> WhisperService:
    """Get or create Whisper service singleton."""
    settings = settings or get_settings()
    return WhisperService(settings)


@lru_cache(maxsize=None)
def get_embedding_service(settings: Optional[Settings] = None) -> EmbeddingService:
    """Get or create embedding service singleton."""
    settings = settings or get_settings()
    return EmbeddingService(settings)
