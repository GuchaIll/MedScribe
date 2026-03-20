"""
Test suite for configuration module.

Tests:
- Settings loading from YAML
- Environment variable overrides
- Validation of required settings
"""

import pytest
from pathlib import Path
import tempfile
import os
from app.config.settings import Settings, ModelConfig, DatabaseConfig, get_settings, reset_settings


class TestModelConfig:
    """Tests for ModelConfig."""

    def test_model_config_defaults(self):
        """Test default model configuration."""
        config = ModelConfig()
        assert config.llm_model == "api"
        assert config.llm_provider == "groq"
        assert config.llm_max_tokens == 2000
        assert config.llm_temperature == 0.1

    def test_model_config_checkpoint_dir_creation(self):
        """Test that checkpoint directory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ModelConfig(model_checkpoint_dir=Path(tmpdir) / "checkpoints")
            assert config.model_checkpoint_dir.exists()


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_database_config_defaults(self):
        """Test default database configuration."""
        config = DatabaseConfig()
        assert config.url == "sqlite:///./medscribe.db"
        assert config.pool_size == 5
        assert config.max_overflow == 10

    def test_database_config_postgresql(self):
        """Test PostgreSQL database configuration."""
        config = DatabaseConfig(url="postgresql://user:pass@localhost/medscribe")
        assert "postgresql" in config.url


class TestSettingsLoading:
    """Tests for Settings loading from YAML."""

    def test_settings_from_yaml(self):
        """Test loading settings from YAML file."""
        yaml_content = """
environment: development
debug: true
model:
  llm_model: local
  llm_max_tokens: 4096
database:
  url: sqlite:///test.db
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                settings = Settings.from_yaml(f.name)
                assert settings.environment == "development"
                assert settings.debug is True
                assert settings.model.llm_model == "local"
                assert settings.model.llm_max_tokens == 4096
                assert settings.database.url == "sqlite:///test.db"
            finally:
                os.unlink(f.name)

    def test_environment_variable_override(self):
        """Test that environment variables override YAML."""
        yaml_content = """
model:
  llm_model: api
database:
  url: sqlite:///default.db
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                os.environ["LLM_MODEL"] = "local"
                os.environ["DATABASE_URL"] = "postgresql://localhost/test"

                settings = Settings.from_yaml(f.name)
                assert settings.model.llm_model == "local"
                assert settings.database.url == "postgresql://localhost/test"
            finally:
                del os.environ["LLM_MODEL"]
                del os.environ["DATABASE_URL"]
                os.unlink(f.name)

    def test_api_keys_from_environment_only(self):
        """Test that API keys are loaded from environment, never YAML."""
        yaml_content = """
groq_api_key: should_not_be_used
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                os.environ["GROQ_API_KEY"] = "test_key_from_env"
                settings = Settings.from_yaml(f.name)
                assert settings.groq_api_key == "test_key_from_env"
            finally:
                del os.environ["GROQ_API_KEY"]
                os.unlink(f.name)


class TestSettingsSingleton:
    """Tests for Settings singleton pattern."""

    def test_get_settings_singleton(self):
        """Test that get_settings returns same instance."""
        reset_settings()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_reset_settings(self):
        """Test that reset_settings clears singleton."""
        reset_settings()
        settings1 = get_settings()
        reset_settings()
        settings2 = get_settings()
        assert settings1 is not settings2


class TestSettingsValidation:
    """Tests for Settings validation."""

    def test_is_production_flag(self):
        """Test production environment detection."""
        settings_dev = Settings(environment="development")
        settings_prod = Settings(environment="production")

        assert not settings_dev.is_production()
        assert settings_prod.is_production()

    def test_debug_flag_false_in_production(self):
        """Test that debug should be False in production."""
        settings = Settings(environment="production", debug=False)
        assert settings.environment == "production"
        assert not settings.debug
