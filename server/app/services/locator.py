"""
Dependency injection and service locator pattern.

Manages:
- Model loading (LLM, Whisper, etc.)
- Service instantiation
- Lifecycle management (initialization, cleanup)

Usage:
    from app.services.locator import get_service_locator
    locator = get_service_locator()
    llm_service = locator.get_llm_service()
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar
import logging

T = TypeVar("T")

logger = logging.getLogger(__name__)


class Service(ABC):
    """Base class for all managed services."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the service (load models, connect to resources)."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources (free memory, close connections)."""
        pass


class ServiceLocator:
    """
    Service locator for managing dependencies.

    Implements registry pattern with lazy initialization.
    """

    def __init__(self) -> None:
        """Initialize service locator."""
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, callable] = {}
        self._initialized: set[str] = set()

    def register(self, name: str, service: Any) -> None:
        """
        Register a service instance.

        Args:
            name: Service identifier
            service: Service instance
        """
        logger.debug(f"Registering service: {name}")
        self._services[name] = service

    def register_factory(self, name: str, factory: callable) -> None:
        """
        Register a factory function for lazy service creation.

        Args:
            name: Service identifier
            factory: Callable that creates the service
        """
        logger.debug(f"Registering factory for: {name}")
        self._factories[name] = factory

    async def get_service(self, name: str) -> Any:
        """
        Get a service instance, initializing if needed.

        Args:
            name: Service identifier

        Returns:
            Service instance

        Raises:
            KeyError: If service not registered
        """
        if name in self._services:
            return self._services[name]

        if name in self._factories:
            logger.debug(f"Creating service from factory: {name}")
            service = self._factories[name]()
            await service.initialize()
            self._services[name] = service
            self._initialized.add(name)
            return service

        raise KeyError(f"Service not registered: {name}")

    async def initialize_all(self) -> None:
        """Initialize all registered services."""
        logger.info("Initializing all services")
        for name, service in self._services.items():
            if name not in self._initialized and hasattr(service, "initialize"):
                logger.debug(f"Initializing service: {name}")
                await service.initialize()
                self._initialized.add(name)

    async def cleanup_all(self) -> None:
        """Clean up all registered services."""
        logger.info("Cleaning up all services")
        for name in list(self._initialized):
            service = self._services.get(name)
            if service and hasattr(service, "cleanup"):
                logger.debug(f"Cleaning up service: {name}")
                try:
                    await service.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up {name}: {e}")
        self._initialized.clear()

    def is_initialized(self, name: str) -> bool:
        """Check if a service has been initialized."""
        return name in self._initialized


# Global service locator instance
_locator: Optional[ServiceLocator] = None


def get_service_locator() -> ServiceLocator:
    """Get the global service locator instance."""
    global _locator
    if _locator is None:
        _locator = ServiceLocator()
    return _locator


def reset_service_locator() -> None:
    """Reset the global service locator (for testing)."""
    global _locator
    _locator = None


# Context manager for service lifecycle
class ServiceLocatorContext:
    """Context manager for service initialization and cleanup."""

    def __init__(self, locator: Optional[ServiceLocator] = None):
        """Initialize context manager."""
        self.locator = locator or get_service_locator()

    async def __aenter__(self) -> ServiceLocator:
        """Initialize services on entering context."""
        await self.locator.initialize_all()
        return self.locator

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up services on exiting context."""
        await self.locator.cleanup_all()
