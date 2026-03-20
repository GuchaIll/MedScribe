"""
Test suite for services module.

Tests:
- Service locator and dependency injection
- Model services (LLM, Whisper, Embedding)
- Service lifecycle management
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from app.services.locator import ServiceLocator, Service, get_service_locator, reset_service_locator
from app.services.models import LLMService, WhisperService
from app.config.settings import Settings


class DummyService(Service):
    """Dummy service for testing."""

    def __init__(self):
        self.initialized = False
        self.cleaned_up = False

    async def initialize(self):
        self.initialized = True

    async def cleanup(self):
        self.cleaned_up = True


class TestServiceLocator:
    """Tests for ServiceLocator."""

    def test_register_service(self):
        """Test registering a service."""
        locator = ServiceLocator()
        service = DummyService()
        locator.register("dummy", service)

        assert locator._services["dummy"] is service

    def test_register_factory(self):
        """Test registering a factory function."""
        locator = ServiceLocator()
        factory = Mock(return_value=DummyService())
        locator.register_factory("dummy", factory)

        assert locator._factories["dummy"] is factory

    @pytest.mark.asyncio
    async def test_get_service_initialized(self):
        """Test getting and initializing a service."""
        locator = ServiceLocator()
        service = DummyService()
        locator.register("dummy", service)

        await locator.initialize_all()
        assert service.initialized

    @pytest.mark.asyncio
    async def test_get_service_from_factory(self):
        """Test creating service from factory."""
        locator = ServiceLocator()
        service = DummyService()
        factory = Mock(return_value=service)
        locator.register_factory("dummy", factory)

        retrieved = await locator.get_service("dummy")
        assert retrieved is service
        assert service.initialized
        factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_service_not_registered(self):
        """Test getting unregistered service raises error."""
        locator = ServiceLocator()
        with pytest.raises(KeyError, match="Service not registered"):
            await locator.get_service("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_all_services(self):
        """Test cleaning up all services."""
        locator = ServiceLocator()
        service1 = DummyService()
        service2 = DummyService()
        locator.register("service1", service1)
        locator.register("service2", service2)

        await locator.initialize_all()
        await locator.cleanup_all()

        assert service1.cleaned_up
        assert service2.cleaned_up

    @pytest.mark.asyncio
    async def test_cleanup_error_tolerance(self):
        """Test that cleanup continues even if one service fails."""
        locator = ServiceLocator()
        service1 = DummyService()
        service2 = DummyService()

        # Make service1 raise during cleanup
        service1.cleanup = AsyncMock(side_effect=Exception("Cleanup failed"))

        locator.register("service1", service1)
        locator.register("service2", service2)

        await locator.initialize_all()
        await locator.cleanup_all()  # Should not raise

        # service2 should still be cleaned up
        assert service2.cleaned_up


class TestLLMService:
    """Tests for LLMService."""

    def test_llm_service_init(self):
        """Test LLMService initialization."""
        settings = Settings()
        service = LLMService(settings)
        assert service.model_name == settings.model.llm_name
        assert service.call_count == 0

    @pytest.mark.asyncio
    async def test_llm_service_budget_tracking(self):
        """Test LLM service budget tracking."""
        settings = Settings(model__llm_provider="groq")
        service = LLMService(settings)

        # Mock the Groq client
        with patch('app.services.models.Groq') as mock_groq:
            mock_client = MagicMock()
            mock_groq.return_value = mock_client

            # Set up mock response
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
            mock_client.chat.completions.create = Mock(return_value=mock_response)

            # Skip Groq initialization check with environment var
            with patch.dict('os.environ', {'GROQ_API_KEY': 'test_key'}):
                await service.initialize()
                result = await service.generate("Test prompt")

                assert result == "Test response"
                assert service.call_count == 1

    def test_llm_budget_remaining(self):
        """Test budget remaining calculation."""
        settings = Settings()
        service = LLMService(settings)
        service.calls_used = 5
        service.max_calls = 30

        assert service.budget_remaining == 25
        assert not service.budget_exhausted

    def test_llm_budget_exhausted(self):
        """Test budget exhausted detection."""
        settings = Settings()
        service = LLMService(settings)
        service.calls_used = 30
        service.max_calls = 30

        assert service.budget_remaining == 0
        assert service.budget_exhausted

    @pytest.mark.asyncio
    async def test_llm_reset_budget(self):
        """Test resetting budget for new session."""
        settings = Settings()
        service = LLMService(settings)
        service.call_count = 15

        service.reset_budget()
        assert service.call_count == 0


class TestSingleton:
    """Tests for service singleton functions."""

    def test_service_locator_singleton(self):
        """Test that get_service_locator returns same instance."""
        reset_service_locator()
        locator1 = get_service_locator()
        locator2 = get_service_locator()
        assert locator1 is locator2

    def test_reset_service_locator(self):
        """Test resetting service locator."""
        reset_service_locator()
        locator1 = get_service_locator()
        reset_service_locator()
        locator2 = get_service_locator()
        assert locator1 is not locator2
