"""
Pytest configuration and fixtures.
"""

import pytest
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings(tmp_path):
    """Provide mock settings for testing."""
    from app.config.settings import Settings, reset_settings

    reset_settings()

    settings = Settings(
        environment="testing",
        debug=True,
        database__url=f"sqlite:///{tmp_path}/test.db",
    )
    return settings


@pytest.fixture
def temp_storage(tmp_path):
    """Provide temporary storage directory."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    return storage_dir


@pytest.fixture(autouse=True)
def cleanup_env():
    """Clean up environment variables after each test."""
    yield
    for key in list(os.environ.keys()):
        if key.startswith(("LLM_", "DATABASE_", "GROQ_", "WHISPER_")):
            del os.environ[key]
